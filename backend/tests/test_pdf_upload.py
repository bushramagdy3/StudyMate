import asyncio

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
