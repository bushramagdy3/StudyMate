import asyncio
import zipfile

import httpx
import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main
from agent.contract import Awaiting, AvatarState, Environment, LectureChunk, TeacherResponse, Topic
from main import Page, app, pages_to_lecture_chunks, read_pages

LONG_TEXT = "HTTP/1.1 pipelining lets a client send several requests without waiting."


def make_pdf(*kinds: str) -> bytes:
    """Build a PDF with one page per kind: 'text', 'image', 'drawing' or 'blank'."""
    document = pymupdf.open()
    for kind in kinds:
        page = document.new_page()
        if kind in ("text", "drawing"):
            page.insert_text((72, 72), LONG_TEXT)
        if kind == "image":
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 50, 50), False)
            page.insert_image(pymupdf.Rect(72, 100, 400, 400), pixmap=pixmap)
        if kind == "drawing":
            for i in range(20):
                page.draw_line((72, 100 + 10 * i), (400, 100 + 10 * i))
    return document.tobytes()


def ok(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def run(pages, handler):
    return asyncio.run(pages_to_lecture_chunks(pages, transport=httpx.MockTransport(handler)))


def image_page(slide: int, text: str = "") -> Page:
    return Page(slide=slide, text=text, image=b"png")


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("FEATHERLESS_API_KEY", "test-key")
    monkeypatch.setenv("FEATHERLESS_CONCURRENCY", "2")
    monkeypatch.setattr(main, "RETRY_DELAY", 0)


def test_only_visual_pages_are_rendered():
    pages = read_pages(make_pdf("text", "image", "drawing", "blank"))
    assert [page.image is not None for page in pages] == [False, True, True, True]
    assert pages[0].text == LONG_TEXT


def test_text_only_pdf_makes_no_llm_calls():
    pages = read_pages(make_pdf("text", "text"))

    def handler(request):
        raise AssertionError("Featherless should not be called")

    chunks = run(pages, handler)
    assert [chunk.text for chunk in chunks] == [LONG_TEXT, LONG_TEXT]


def test_mixed_pages_keep_slide_order():
    pages = [Page(slide=1, text="plain text", image=None), image_page(2), image_page(3)]

    def handler(request):
        slide = "2" if "slide 2" in request.content.decode() else "3"
        return ok(f"description of slide {slide}")

    chunks = run(pages, handler)
    assert [(c.slide, c.text) for c in chunks] == [
        (1, "plain text"),
        (2, "description of slide 2"),
        (3, "description of slide 3"),
    ]


def test_never_more_requests_at_once_than_the_concurrency_limit():
    in_flight = peak = 0

    async def handler(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return ok("description")

    run([image_page(i) for i in range(1, 9)], handler)
    assert peak == 2


def test_retries_after_a_rate_limit():
    responses = iter([httpx.Response(429), ok("worked on retry")])
    chunks = run([image_page(1)], lambda request: next(responses))
    assert chunks[0].text == "worked on retry"


def test_falls_back_to_page_text_when_every_attempt_fails():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    chunks = run([image_page(1, text="backup text")], handler)
    assert chunks[0].text == "backup text"
    assert calls == main.MAX_ATTEMPTS


def test_wrong_api_key_fails_immediately():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    with pytest.raises(HTTPException) as error:
        run([image_page(1)], handler)
    assert "invalid key" in error.value.detail
    assert calls == 1


def test_upload_endpoint_returns_lecture_chunks():
    client = TestClient(app)
    response = client.post(
        "/api/upload-pdf",
        files={"pdf": ("lecture.pdf", make_pdf("text"), "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json() == {"lecture_chunks": [{"slide": 1, "text": LONG_TEXT}]}


def test_upload_endpoint_rejects_non_pdf():
    client = TestClient(app)
    response = client.post("/api/upload-pdf", files={"pdf": ("notes.txt", b"hi", "text/plain")})
    assert response.status_code == 400


def test_start_session_endpoint_processes_pdf_before_starting_agent(monkeypatch):
    captured = {}

    async def fake_process_pdf(pdf):
        captured["filename"] = pdf.filename
        return [LectureChunk(slide=1, text="HTTP overview")]

    class FakeTeacher:
        def start_session(self, request):
            captured["request"] = request
            return TeacherResponse(
                session_id="session-1",
                speech=["Welcome."],
                avatar_state=AvatarState.SPEAKING,
                awaiting=Awaiting.CONTINUE,
                outline=[Topic(index=0, title="HTTP")],
                current_topic=0,
                current_slide=1,
                can_raise_hand=True,
            )

    monkeypatch.setattr(main, "process_pdf_upload", fake_process_pdf)
    monkeypatch.setattr(main, "get_teacher", lambda: FakeTeacher())

    client = TestClient(app)
    response = client.post(
        "/api/sessions",
        data={"environment": "private-tutor"},
        files={"pdf": ("lecture.pdf", b"%PDF", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "session-1"
    assert captured["filename"] == "lecture.pdf"
    assert captured["request"].environment is Environment.STUDY_ROOM
    assert captured["request"].lecture == [LectureChunk(slide=1, text="HTTP overview")]


def test_combined_media_preserves_order_and_source_metadata(monkeypatch):
    class Upload:
        def __init__(self, filename, content_type):
            self.filename = filename
            self.content_type = content_type

    async def fake_pdf(upload):
        return [LectureChunk(slide=1, text=f"PDF content from {upload.filename}")]

    async def fake_presentation(upload):
        return [
            LectureChunk(slide=1, text=f"PPT page one from {upload.filename}"),
            LectureChunk(slide=2, text=f"PPT page two from {upload.filename}"),
        ]

    async def fake_video(upload):
        return [
            LectureChunk(
                slide=1,
                text="Video transcript segment",
                source_type="video",
                start_seconds=12.5,
                end_seconds=18.0,
            )
        ]

    monkeypatch.setattr(main, "process_pdf_upload", fake_pdf)
    monkeypatch.setattr(main, "process_presentation_upload", fake_presentation)
    monkeypatch.setattr(main, "process_video_upload", fake_video)

    chunks = asyncio.run(
        main.process_media_uploads(
            [
                Upload("lecture-notes.pdf", "application/pdf"),
                Upload("slides.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
                Upload("recap.mp4", "video/mp4"),
            ]
        )
    )

    assert [(chunk.slide, chunk.source_name, chunk.source_type) for chunk in chunks] == [
        (1, "lecture-notes.pdf", "pdf"),
        (2, "slides.pptx", "ppt"),
        (3, "slides.pptx", "ppt"),
        (4, "recap.mp4", "video"),
    ]
    assert [chunk.source_page for chunk in chunks] == [1, 1, 2, None]
    assert chunks[-1].start_seconds == 12.5
    assert chunks[-1].end_seconds == 18.0


def test_visual_media_cache_keeps_the_presentation_at_its_upload_index(monkeypatch):
    class Upload:
        def __init__(self, filename, content_type, payload):
            self.filename = filename
            self.content_type = content_type
            self.payload = payload

        async def read(self):
            return self.payload

    async def fake_process_pdf_bytes(payload):
        return [LectureChunk(slide=1, text=payload.decode())]

    async def fake_presentation_to_pdf(payload, _filename):
        return b"converted-" + payload

    monkeypatch.setattr(main, "process_pdf_bytes", fake_process_pdf_bytes)
    monkeypatch.setattr(main, "presentation_to_pdf_bytes", fake_presentation_to_pdf)
    viewer_sources = {}

    chunks = asyncio.run(
        main.process_media_uploads(
            [
                Upload("notes.pdf", "application/pdf", b"pdf material"),
                Upload(
                    "diagram.pptx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    b"presentation material",
                ),
            ],
            viewer_sources,
        )
    )

    assert viewer_sources == {0: b"pdf material", 1: b"converted-presentation material"}
    assert [(chunk.slide, chunk.source_index, chunk.source_page) for chunk in chunks] == [
        (1, 0, 1),
        (2, 1, 1),
    ]


def test_video_transcription_keeps_whisper_segment_timestamps(monkeypatch):
    monkeypatch.setenv("GROQ_STT_API_KEY", "test-key")

    def handler(request):
        assert request.url == httpx.URL(main.GROQ_STT_URL)
        return httpx.Response(
            200,
            json={
                "segments": [
                    {"start": 0.0, "end": 3.2, "text": " First idea. "},
                    {"start": 3.2, "end": 7.8, "text": "Second idea."},
                ]
            },
        )

    chunks = asyncio.run(
        main.transcribe_video_audio(
            b"audio",
            "lesson.mp4",
            transport=httpx.MockTransport(handler),
        )
    )

    assert [(chunk.text, chunk.start_seconds, chunk.end_seconds) for chunk in chunks] == [
        ("First idea.", 0.0, 3.2),
        ("Second idea.", 3.2, 7.8),
    ]
    assert all(chunk.source_name == "lesson.mp4" for chunk in chunks)


def test_start_session_endpoint_accepts_multiple_media_sources(monkeypatch):
    captured = {}

    async def fake_process_media(media, viewer_sources=None):
        captured["filenames"] = [upload.filename for upload in media]
        return [LectureChunk(slide=1, text="Combined lecture")]

    class FakeTeacher:
        def start_session(self, request):
            captured["request"] = request
            return TeacherResponse(
                session_id="combined-session",
                speech=["Welcome."],
                avatar_state=AvatarState.SPEAKING,
                awaiting=Awaiting.CONTINUE,
                outline=[Topic(index=0, title="Combined lecture")],
                current_topic=0,
                current_slide=1,
                can_raise_hand=True,
            )

    monkeypatch.setattr(main, "process_media_uploads", fake_process_media)
    monkeypatch.setattr(main, "get_teacher", lambda: FakeTeacher())

    client = TestClient(app)
    response = client.post(
        "/api/sessions",
        data={"environment": "private-tutor"},
        files=[
            ("media", ("one.pdf", b"%PDF", "application/pdf")),
            ("media", ("two.pdf", b"%PDF", "application/pdf")),
            ("media", ("recap.mp4", b"video", "video/mp4")),
        ],
    )

    assert response.status_code == 200
    assert response.json()["session_id"] == "combined-session"
    assert captured["filenames"] == ["one.pdf", "two.pdf", "recap.mp4"]
    assert captured["request"].lecture == [LectureChunk(slide=1, text="Combined lecture")]


def test_session_source_endpoint_serves_cached_pdf(monkeypatch):
    class FakeTeacher:
        def get_session(self, _session_id):
            return object()

    monkeypatch.setattr(main, "get_teacher", lambda: FakeTeacher())
    main.session_viewer_sources["source-session"] = {1: b"%PDF-test"}

    response = TestClient(app).get("/api/sessions/source-session/sources/1.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content == b"%PDF-test"
    main.session_viewer_sources.pop("source-session", None)


def test_default_session_source_endpoint_uses_the_first_cached_visual_file(monkeypatch):
    class FakeTeacher:
        def get_session(self, _session_id):
            return object()

    monkeypatch.setattr(main, "get_teacher", lambda: FakeTeacher())
    main.session_viewer_sources["default-source-session"] = {3: b"%PDF-later", 1: b"%PDF-first"}

    response = TestClient(app).get("/api/sessions/default-source-session/sources/default.pdf")

    assert response.status_code == 200
    assert response.content == b"%PDF-first"
    main.session_viewer_sources.pop("default-source-session", None)


def test_presentation_uses_powerpoint_when_libreoffice_is_unavailable(monkeypatch):
    monkeypatch.setattr(main, "libreoffice_executable", lambda: None)
    monkeypatch.setattr(main, "powerpoint_executable", lambda: "POWERPNT.EXE")
    monkeypatch.setattr(main, "convert_with_powerpoint", lambda _source, _output: b"%PDF-powerpoint")

    assert main.convert_presentation_bytes(b"presentation", "lecture.pptx") == b"%PDF-powerpoint"


def test_pptx_text_fallback_creates_a_viewable_pdf(tmp_path):
    source = tmp_path / "fallback.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            (
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
                'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                '<a:t>Fallback title</a:t><a:t>Fallback explanation</a:t></p:sld>'
            ),
        )

    pdf_bytes = main.convert_pptx_text_to_pdf(source)

    assert pdf_bytes.startswith(b"%PDF")
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        assert document.page_count == 1
        assert "Fallback title" in document[0].get_text()
