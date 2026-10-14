import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

import httpx
from agent.contract import (
    Environment,
    LectureChunk,
    Quiz,
    QuizAnswers,
    QuizRequest,
    QuizResult,
    StartSessionRequest,
    StudentEvent,
    TeacherResponse,
)
from agent.llm import LLMError
from agent.teacher import EventNotAllowed, SessionNotFound, Teacher
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel
import truststore

load_dotenv(Path(__file__).parent / ".env")
# On Windows, use the OS certificate store for outbound API calls. This keeps
# Fish Audio TLS verification enabled while supporting the local trust chain.
truststore.inject_into_ssl()

app = FastAPI()

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    *[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "").split(",")
        if origin.strip()
    ],
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FEATHERLESS_URL = "https://api.featherless.ai/v1/chat/completions"

# Featherless errors worth retrying: rate/concurrency limit and temporary server problems.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
RETRY_DELAY = 2  # seconds; doubles after each failed attempt

# A page skips the vision model when it has enough text and nothing visual:
MIN_TEXT_CHARS = 40  # less text than this probably means a scanned or picture-only slide
MIN_IMAGE_AREA = 0.10  # an image covering 10%+ of the page is content, not a small logo
MIN_DRAWINGS = 15  # this many vector shapes usually means a diagram, chart or table


class PdfUploadResponse(BaseModel):
    lecture_chunks: list[LectureChunk]


class MediaUploadResponse(BaseModel):
    lecture_chunks: list[LectureChunk]


class TTR(BaseModel):
    text: str


teacher: Teacher | None = None
# PDFs are held only for the lifetime of an active session. Uploaded PDFs and
# server-converted PowerPoints both use this cache so the existing PDF viewer
# can follow an explanation across source files.
session_viewer_sources: dict[str, dict[int, bytes]] = {}


def get_teacher() -> Teacher:
    global teacher

    if teacher is None:
        try:
            teacher = Teacher()
        except LLMError as error:
            raise HTTPException(
                status_code=500,
                detail=str(error),
            )

    return teacher


def session_not_found(session_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=f"Session '{session_id}' was not found.",
    )


def parse_environment(value: str | None) -> Environment:
    aliases = {
        "lecture-hall": Environment.LECTURE_HALL,
        "private-tutor": Environment.STUDY_ROOM,
        "study-cafe": Environment.CAFE,
    }

    if value is None:
        raise HTTPException(
            status_code=422,
            detail="environment is required.",
        )

    if value in aliases:
        return aliases[value]

    try:
        return Environment(value)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="environment must be lecture_hall, study_room or cafe.",
        )


@dataclass
class Page:
    slide: int
    text: str  # text extracted directly from the PDF
    image: bytes | None  # PNG of the page, only when it needs the vision model


def needs_vision(page) -> bool:
    """Whether a page has visual content that plain text extraction would miss."""
    if len(page.get_text().strip()) < MIN_TEXT_CHARS:
        return True

    page_area = page.rect.width * page.rect.height
    for image in page.get_image_info():
        x0, y0, x1, y1 = image["bbox"]
        if (x1 - x0) * (y1 - y0) >= MIN_IMAGE_AREA * page_area:
            return True

    return len(page.get_drawings()) >= MIN_DRAWINGS


def read_pages(pdf_bytes: bytes) -> list[Page]:
    import pymupdf

    pages = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as pdf_document:
        for slide_number, page in enumerate(pdf_document, start=1):
            image = None
            if needs_vision(page):
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                image = pixmap.tobytes("png")
            pages.append(
                Page(
                    slide=slide_number,
                    text=page.get_text().strip(),
                    image=image,
                )
            )

    return pages


def featherless_settings() -> tuple[str, str, int]:
    api_key = os.getenv("FEATHERLESS_API_KEY") or os.getenv("API_KEY")
    model = os.getenv("FEATHERLESS_MODEL", "moonshotai/Kimi-K3")

    # How many pages to send to Featherless at the same time. Set this to the
    # number of concurrent requests your plan allows for this model.
    concurrency = int(os.getenv("FEATHERLESS_CONCURRENCY", "2"))

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Missing Featherless API key.",
        )

    return api_key, model, max(1, concurrency)


def build_prompt(page: Page) -> str:
    return f"""
You are converting a lecture slide into a LectureChunk for an AI teacher.

Read slide {page.slide} visually and write the text field for this page.
Focus on the academic content, concepts, and scope of the slide.
Explain what the slide is teaching and what the teacher should understand
before generating an explanation from it.

If there is a diagram, table, image, equation, or example, explain what it means
conceptually. Do not describe its colors, positions, icons, fonts, or layout
unless that visual detail is necessary to understand the concept.

Text extracted from the slide (it may be incomplete or out of order; use it
to get names, terms and numbers exactly right):
{page.text or "(no extractable text)"}

Return only the LectureChunk text.
Do not return JSON.
Do not add headings.
Do not add extra fields.
Do not invent content that is not visible on the slide.
"""


async def describe_page(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    api_key: str,
    model: str,
    page: Page,
) -> str:
    image_base64 = base64.b64encode(page.image).decode("utf-8")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": build_prompt(page),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_base64}"
                        },
                    },
                ],
            }
        ],
        "temperature": 0.1,
    }

    # The semaphore makes pages wait their turn, so at most `concurrency`
    # requests are running at Featherless at once.
    async with semaphore:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await client.post(
                    FEATHERLESS_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}"
                    },
                    json=payload,
                )
            except httpx.HTTPError:
                response = None  # timeout or connection problem: retry

            if response is not None and response.status_code == 200:
                try:
                    content = response.json()["choices"][0]["message"]["content"]
                except (
                    ValueError,
                    KeyError,
                    IndexError,
                    TypeError,
                ):
                    content = None

                if content and content.strip():
                    return content.strip()

            elif (
                response is not None
                and response.status_code not in RETRYABLE_STATUS
            ):
                # Wrong key, unknown model, bad request: retrying won't help,
                # and every other page would fail the same way.
                try:
                    error = response.json()["error"]["message"]
                except Exception:
                    error = response.text

                raise HTTPException(
                    status_code=502,
                    detail=f"Featherless error for model {model}: {error}",
                )

            if attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(
                    RETRY_DELAY * 2**attempt
                )

    # Every attempt failed: keep the page's plain text so the upload still succeeds.
    return page.text


async def pages_to_lecture_chunks(
    pages: list[Page],
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[LectureChunk]:

    if not any(page.image for page in pages):
        return [
            LectureChunk(
                slide=page.slide,
                text=page.text,
            )
            for page in pages
        ]

    api_key, model, concurrency = featherless_settings()

    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=120,
        transport=transport,
    ) as client:

        async def chunk_text(page: Page) -> str:
            if page.image is None:
                return page.text

            return await describe_page(
                client,
                semaphore,
                api_key,
                model,
                page,
            )

        # Start every page at once; the semaphore limits how many actually run.
        texts = await asyncio.gather(
            *(chunk_text(page) for page in pages)
        )

    return [
        LectureChunk(
            slide=page.slide,
            text=text,
        )
        for page, text in zip(pages, texts)
    ]


def is_pdf_upload(upload: UploadFile) -> bool:
    return (upload.content_type or "").lower() == "application/pdf" or (
        upload.filename or ""
    ).lower().endswith(".pdf")


async def process_pdf_bytes(pdf_bytes: bytes) -> list[LectureChunk]:
    if not pdf_bytes:
        raise HTTPException(
            status_code=400,
            detail="PDF file is empty.",
        )

    try:
        # Rendering pages is slow CPU work; a thread keeps the server responsive.
        pages = await asyncio.to_thread(read_pages, pdf_bytes)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read PDF file.",
        )

    return await pages_to_lecture_chunks(pages)


async def process_pdf_upload(pdf: UploadFile) -> list[LectureChunk]:
    if not is_pdf_upload(pdf):
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF file.",
        )

    return await process_pdf_bytes(await pdf.read())


PRESENTATION_EXTENSIONS = {".ppt", ".pptx"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}
MAX_MEDIA_BYTES = 500 * 1024 * 1024
PRESENTATION_TIMEOUT_SECONDS = 120
VIDEO_TRANSCRIPTION_TIMEOUT_SECONDS = 90.0


def file_extension(upload: UploadFile) -> str:
    return Path(upload.filename or "").suffix.lower()


def media_type(upload: UploadFile) -> Literal["pdf", "ppt", "video"]:
    extension = file_extension(upload)
    content_type = (upload.content_type or "").lower()
    if extension == ".pdf" or content_type == "application/pdf":
        return "pdf"
    if extension in PRESENTATION_EXTENSIONS or content_type in {
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return "ppt"
    if extension in VIDEO_EXTENSIONS or content_type.startswith("video/"):
        return "video"
    raise HTTPException(
        status_code=400,
        detail="Upload PDF, PPT/PPTX, or video files only.",
    )


def libreoffice_executable() -> str | None:
    configured = os.getenv("LIBREOFFICE_PATH")
    if configured and Path(configured).is_file():
        return configured
    return shutil.which("soffice") or shutil.which("libreoffice")


def powerpoint_executable() -> str | None:
    """Find a local Windows PowerPoint installation for presentation export."""
    configured = os.getenv("POWERPOINT_PATH")
    if configured and Path(configured).is_file():
        return configured
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Microsoft Office/root/Office16/POWERPNT.EXE",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Office/root/Office16/POWERPNT.EXE",
    ]
    return next((str(candidate) for candidate in candidates if candidate.is_file()), None)


def convert_presentation_bytes(presentation: bytes, filename: str) -> bytes:
    executable = libreoffice_executable()

    with tempfile.TemporaryDirectory(prefix="studymate-ppt-") as directory:
        source = Path(directory, Path(filename).name)
        output = source.with_suffix(".pdf")
        source.write_bytes(presentation)
        if executable:
            try:
                result = subprocess.run(
                    [
                        executable,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        directory,
                        str(source),
                    ],
                    capture_output=True,
                    check=False,
                    timeout=PRESENTATION_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as error:
                raise HTTPException(
                    status_code=504,
                    detail="Presentation conversion took too long. Please try a smaller file.",
                ) from error
            if result.returncode == 0 and output.is_file():
                return output.read_bytes()

        if powerpoint_executable():
            try:
                return convert_with_powerpoint(source, output)
            except HTTPException:
                if source.suffix.lower() != ".pptx":
                    raise

        if source.suffix.lower() == ".pptx":
            return convert_pptx_text_to_pdf(source)

        raise HTTPException(
            status_code=503,
            detail=(
                "Could not convert this legacy .ppt file. Install LibreOffice, or open it in "
                "PowerPoint and save it as .pptx before uploading."
            ),
        )


def convert_with_powerpoint(source: Path, output: Path) -> bytes:
    """Export a PPT/PPTX using installed PowerPoint without showing a window."""
    source_path = str(source).replace("'", "''")
    output_path = str(output).replace("'", "''")
    script = f"""
$ErrorActionPreference = 'Stop'
$app = $null
$presentation = $null
try {{
  $app = New-Object -ComObject PowerPoint.Application
  $presentation = $app.Presentations.Open('{source_path}', $false, $false, $false)
  $presentation.SaveAs('{output_path}', 32)
}} finally {{
  if ($presentation) {{ $presentation.Close() }}
  if ($app) {{ $app.Quit() }}
}}
"""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            check=False,
            timeout=PRESENTATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise HTTPException(
            status_code=504,
            detail="PowerPoint took too long to export this presentation. Please try a smaller file.",
        ) from error
    if result.returncode != 0 or not output.is_file():
        message = result.stderr.decode("utf-8", "replace").strip()
        raise HTTPException(
            status_code=400,
            detail=f"Could not export this presentation with PowerPoint.{f' {message}' if message else ''}",
        )
    return output.read_bytes()


def convert_pptx_text_to_pdf(source: Path) -> bytes:
    """Last-resort PPTX fallback that keeps each slide's text viewable."""
    try:
        with zipfile.ZipFile(source) as archive:
            slide_names = sorted(
                (name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")),
                key=lambda name: int(Path(name).stem.removeprefix("slide")),
            )
            slide_text = []
            for name in slide_names:
                root = ElementTree.fromstring(archive.read(name))
                lines = [node.text.strip() for node in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t") if node.text and node.text.strip()]
                slide_text.append("\n".join(lines) or "This slide has no extractable text.")
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as error:
        raise HTTPException(status_code=400, detail="Could not read the PPTX file.") from error

    import pymupdf

    document = pymupdf.open()
    for index, text in enumerate(slide_text, start=1):
        page = document.new_page(width=960, height=540)
        page.insert_textbox(
            pymupdf.Rect(56, 50, 904, 490),
            f"Slide {index}\n\n{text}",
            fontsize=18,
            fontname="helv",
            color=(0.12, 0.08, 0.06),
            lineheight=1.35,
        )
    return document.tobytes()


async def process_presentation_upload(presentation: UploadFile) -> list[LectureChunk]:
    if file_extension(presentation) not in PRESENTATION_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Upload a PPT or PPTX file.")
    presentation_bytes = await presentation.read()
    if not presentation_bytes:
        raise HTTPException(status_code=400, detail="Presentation file is empty.")
    if len(presentation_bytes) > MAX_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="Presentation is too large. Keep it under 500 MB.")
    pdf_bytes = await presentation_to_pdf_bytes(
        presentation_bytes, presentation.filename or "presentation.pptx"
    )
    return await process_pdf_bytes(pdf_bytes)


async def presentation_to_pdf_bytes(presentation_bytes: bytes, filename: str) -> bytes:
    """Convert a presentation once, for extraction and the session viewer."""
    if not presentation_bytes:
        raise HTTPException(status_code=400, detail="Presentation file is empty.")
    if len(presentation_bytes) > MAX_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="Presentation is too large. Keep it under 500 MB.")
    return await asyncio.to_thread(convert_presentation_bytes, presentation_bytes, filename)


def ffmpeg_executable() -> str:
    configured = os.getenv("FFMPEG_PATH")
    if configured and Path(configured).is_file():
        return configured
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="Video processing requires FFmpeg. Install the backend dependencies and try again.",
        ) from error


def extract_video_audio(video_bytes: bytes, filename: str) -> bytes:
    """Extract compact mono MP3 audio so Whisper receives audio, not a video container."""
    with tempfile.TemporaryDirectory(prefix="studymate-video-") as directory:
        source = Path(directory, Path(filename).name)
        output = Path(directory, "audio.mp3")
        source.write_bytes(video_bytes)
        try:
            result = subprocess.run(
                [
                    ffmpeg_executable(),
                    "-y",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-b:a",
                    "32k",
                    str(output),
                ],
                capture_output=True,
                check=False,
                timeout=PRESENTATION_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as error:
            raise HTTPException(
                status_code=504,
                detail="Video audio extraction took too long. Please try a shorter video.",
            ) from error
        if result.returncode != 0 or not output.is_file():
            raise HTTPException(status_code=400, detail="Could not extract audio from this video.")
        return output.read_bytes()


async def transcribe_video_audio(
    audio_bytes: bytes,
    source_name: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[LectureChunk]:
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="The video has no readable audio track.")
    if len(audio_bytes) > GROQ_STT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The extracted video audio is too large. Please upload a shorter video.",
        )

    try:
        async with httpx.AsyncClient(
            timeout=VIDEO_TRANSCRIPTION_TIMEOUT_SECONDS,
            transport=transport,
        ) as client:
            response = await client.post(
                GROQ_STT_URL,
                headers={"Authorization": f"Bearer {groq_stt_api_key()}"},
                data={
                    "model": GROQ_STT_MODEL,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment",
                },
                files={"file": (f"{Path(source_name).stem}.mp3", audio_bytes, "audio/mpeg")},
            )
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Video transcription could not be reached. Please try again.",
        ) from error

    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail="Video transcription is temporarily unavailable. Please try again later.",
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="Video transcription failed. Please try again.")

    try:
        payload = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="Video transcription returned an invalid response.") from error

    segments = payload.get("segments") or []
    chunks = []
    for segment in segments:
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        chunks.append(
            LectureChunk(
                slide=len(chunks) + 1,
                text=text,
                source_name=source_name,
                source_type="video",
                start_seconds=float(segment.get("start", 0)),
                end_seconds=float(segment.get("end", segment.get("start", 0))),
            )
        )
    if chunks:
        return chunks

    transcript = str(payload.get("text", "")).strip()
    if not transcript:
        raise HTTPException(status_code=502, detail="Video transcription returned no text.")
    return [
        LectureChunk(
            slide=1,
            text=transcript,
            source_name=source_name,
            source_type="video",
            start_seconds=0,
        )
    ]


async def process_video_upload(video: UploadFile) -> list[LectureChunk]:
    video_bytes = await video.read()
    if not video_bytes:
        raise HTTPException(status_code=400, detail="Video file is empty.")
    if len(video_bytes) > MAX_MEDIA_BYTES:
        raise HTTPException(status_code=413, detail="Video is too large. Keep it under 500 MB.")
    audio_bytes = await asyncio.to_thread(
        extract_video_audio,
        video_bytes,
        video.filename or "video.mp4",
    )
    return await transcribe_video_audio(audio_bytes, video.filename or "video")


def annotate_source_chunks(
    chunks: list[LectureChunk],
    source_name: str,
    source_type: Literal["pdf", "ppt", "video"],
    first_slide: int,
    source_index: int | None = None,
) -> list[LectureChunk]:
    """Give each source chunk a globally unique slide id while retaining its origin."""
    annotated = []
    for offset, chunk in enumerate(chunks):
        annotated.append(
            LectureChunk(
                slide=first_slide + offset,
                text=chunk.text,
                source_name=source_name,
                source_index=source_index,
                source_type=source_type,
                source_page=chunk.slide if source_type != "video" else None,
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
            )
        )
    return annotated


async def process_media_uploads(
    media: list[UploadFile],
    viewer_sources: dict[int, bytes] | None = None,
) -> list[LectureChunk]:
    if not media:
        raise HTTPException(status_code=400, detail="Upload at least one media file.")

    lecture = []
    next_slide = 1
    for source_index, upload in enumerate(media):
        kind = media_type(upload)
        if kind == "pdf" and viewer_sources is not None:
            if not is_pdf_upload(upload):
                raise HTTPException(status_code=400, detail="Upload a PDF file.")
            pdf_bytes = await upload.read()
            chunks = await process_pdf_bytes(pdf_bytes)
            viewer_sources[source_index] = pdf_bytes
        elif kind == "ppt" and viewer_sources is not None:
            presentation_bytes = await upload.read()
            pdf_bytes = await presentation_to_pdf_bytes(
                presentation_bytes, upload.filename or "presentation.pptx"
            )
            chunks = await process_pdf_bytes(pdf_bytes)
            viewer_sources[source_index] = pdf_bytes
        elif kind == "pdf":
            chunks = await process_pdf_upload(upload)
        elif kind == "ppt":
            chunks = await process_presentation_upload(upload)
        else:
            chunks = await process_video_upload(upload)
        annotated = annotate_source_chunks(
            chunks,
            upload.filename or "Untitled source",
            kind,
            next_slide,
            source_index,
        )
        lecture.extend(annotated)
        next_slide += len(annotated)

    if not lecture:
        raise HTTPException(status_code=400, detail="No learning content could be extracted from the uploaded media.")
    return lecture


# ---------------------------------------------------------
# TEXT-TO-SPEECH
# ---------------------------------------------------------

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_VOICE_ID = "bddf65d5a84c4a9aa36b7136bdac57a9"  # Women KatKat
FISH_MODEL = "s2.1-pro-free"
FISH_TTS_TIMEOUT_SECONDS = 20.0
FISH_TTS_MAX_ATTEMPTS = 2

# Groq Whisper is only used for optional student voice input. The rest of the
# app continues to use Featherless for teaching and Fish for Regina's speech.
GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"
GROQ_STT_TIMEOUT_SECONDS = 35.0
GROQ_STT_MAX_BYTES = 25 * 1024 * 1024


def groq_stt_api_key() -> str:
    api_key = os.getenv("GROQ_STT_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Missing GROQ_STT_API_KEY in backend/.env.",
        )
    return api_key


async def transcribe_student_audio(
    audio: UploadFile,
    session: TeacherResponse,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Transcribe one recorded student response with concise lecture context."""
    content_type = (audio.content_type or "audio/webm").split(";", 1)[0]
    if content_type not in {
        "audio/webm",
        "audio/ogg",
        "audio/wav",
        "audio/mpeg",
        "audio/mp4",
    }:
        raise HTTPException(status_code=400, detail="Unsupported recording format.")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="The recording is empty.")
    if len(audio_bytes) > GROQ_STT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The recording is too large. Please keep it under 25 MB.",
        )

    topic_names = ", ".join(topic.title for topic in session.outline[:12])
    prompt = (
        "This is a student response in an interactive lecture. Transcribe the "
        "student faithfully, using these lecture terms when they are spoken: "
        f"{topic_names or 'general academic terms'}. Preserve the student's "
        "intent. Return only the cleaned transcript, without commentary."
    )
    filename = audio.filename or "student-answer.webm"

    try:
        async with httpx.AsyncClient(
            timeout=GROQ_STT_TIMEOUT_SECONDS,
            transport=transport,
        ) as client:
            response = await client.post(
                GROQ_STT_URL,
                headers={"Authorization": f"Bearer {groq_stt_api_key()}"},
                data={"model": GROQ_STT_MODEL, "prompt": prompt},
                files={"file": (filename, audio_bytes, content_type)},
            )
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=502,
            detail="Voice transcription could not be reached. Please type your response instead.",
        ) from error

    if response.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "voice_limit_reached",
                "message": (
                    "Voice input has reached its free-tier limit. "
                    "Please type your response instead."
                ),
            },
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=(
                "Voice transcription failed. Please try again or type your "
                "response instead."
            ),
        )

    try:
        transcript = response.json().get("text", "").strip()
    except (ValueError, AttributeError):
        transcript = ""
    # Whisper occasionally echoes its own prompt for empty or unusable audio.
    # Never put this internal instruction into the student's text box.
    if "return only the cleaned transcript" in transcript.lower():
        transcript = ""
    if not transcript:
        raise HTTPException(
            status_code=502,
            detail=(
                "Voice transcription returned no text. Please try again or "
                "type your response instead."
            ),
        )

    return transcript


def fish_audio_api_key() -> str:
    api_key = os.getenv("FISH_AUDIO_API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Missing FISH_AUDIO_API_KEY in backend/.env.",
        )

    return api_key


async def generate_speech_audio(
    text: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[bytes, str]:
    """Generate an MP3 with Fish Audio S2.1 Pro and the shared Regina voice."""
    api_key = fish_audio_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "model": FISH_MODEL,
    }

    payload = {
        # Fish direction tags stay in text. They guide delivery but are removed
        # by the frontend before the same text is displayed as a subtitle.
        "text": text,
        "reference_id": FISH_VOICE_ID,
        "format": "mp3",
        "normalize": True,
        "latency": "balanced",
    }

    response: httpx.Response | None = None
    async with httpx.AsyncClient(
        timeout=FISH_TTS_TIMEOUT_SECONDS,
        transport=transport,
    ) as client:
        for attempt in range(FISH_TTS_MAX_ATTEMPTS):
            try:
                response = await client.post(
                    FISH_TTS_URL,
                    headers=headers,
                    json=payload,
                )
            except httpx.HTTPError as error:
                if attempt + 1 == FISH_TTS_MAX_ATTEMPTS:
                    raise HTTPException(
                        status_code=502,
                        detail=f"Fish Audio TTS could not be reached: {error}",
                    ) from error

                await asyncio.sleep(1)
                continue

            if response.status_code not in {429, 500, 502, 503, 504}:
                break

            if attempt + 1 < FISH_TTS_MAX_ATTEMPTS:
                await asyncio.sleep(1)

    if response is None or response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Fish Audio TTS failed: {response.text if response else 'no response'}",
        )

    if not response.content:
        raise HTTPException(
            status_code=502,
            detail="Fish Audio returned empty audio.",
        )

    return response.content, "mp3"


@app.get('/')
def main():
    return {"message": "hello world"}


@app.post("/api/upload-pdf", response_model=PdfUploadResponse, response_model_exclude_none=True)
async def upload_pdf(
    pdf: UploadFile = File(...)
):
    return PdfUploadResponse(
        lecture_chunks=await process_pdf_upload(pdf)
    )


@app.post("/api/upload-media", response_model=MediaUploadResponse, response_model_exclude_none=True)
async def upload_media(media: list[UploadFile] = File(...)):
    """Preview extraction for a combined media upload without starting a session."""
    return MediaUploadResponse(lecture_chunks=await process_media_uploads(media))


@app.post("/api/sessions", response_model=TeacherResponse)
async def start_session(
    media: list[UploadFile] | None = File(None),
    pdf: UploadFile | None = File(None),
    environment: str | None = Form(None),
    enviroment: str | None = Form(None),
):
    # Keep the old single-PDF field working for existing clients while the new
    # upload page sends one or more files under `media`.
    viewer_sources: dict[int, bytes] = {}
    if media:
        lecture = await process_media_uploads(media, viewer_sources)
    elif pdf:
        lecture = await process_pdf_upload(pdf)
    else:
        lecture = None
    if lecture is None:
        raise HTTPException(status_code=422, detail="Upload at least one PDF, PPT/PPTX, or video file.")
    request = StartSessionRequest(
        environment=parse_environment(environment or enviroment),
        lecture=lecture,
    )

    try:
        response = get_teacher().start_session(request)
        if viewer_sources:
            session_viewer_sources[response.session_id] = viewer_sources
        return response
    except LLMError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


@app.post("/api/sessions/{session_id}/events", response_model=TeacherResponse)
def send_session_event(session_id: str, event: StudentEvent):
    try:
        return get_teacher().send_event(session_id, event)
    except SessionNotFound:
        raise session_not_found(session_id)
    except EventNotAllowed as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )
    except LLMError as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        )


@app.get("/api/sessions/{session_id}", response_model=TeacherResponse)
def get_session(session_id: str):
    try:
        return get_teacher().get_session(session_id)
    except SessionNotFound:
        raise session_not_found(session_id)


def session_source_pdf(session_id: str, source_index: int | None = None) -> Response:
    """Serve one visual source, or the first available source, as a PDF."""
    try:
        get_teacher().get_session(session_id)
    except SessionNotFound:
        raise session_not_found(session_id)

    sources = session_viewer_sources.get(session_id, {})
    if source_index is None and sources:
        source_index = min(sources)
    source = sources.get(source_index)
    if source is None:
        raise HTTPException(status_code=404, detail="That source has no viewable PDF pages.")
    return Response(
        content=source,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline"},
    )


@app.get("/api/sessions/{session_id}/sources/default.pdf")
def get_default_session_source_pdf(session_id: str):
    """Provide a stable visual fallback when a response has no source reference."""
    return session_source_pdf(session_id)


@app.get("/api/sessions/{session_id}/sources/{source_index}.pdf")
def get_session_source_pdf(session_id: str, source_index: int):
    """Serve one exact visual source for the in-session page viewer."""
    return session_source_pdf(session_id, source_index)


@app.post("/api/sessions/{session_id}/transcribe")
async def transcribe_session_audio(
    session_id: str,
    audio: UploadFile = File(...),
):
    try:
        session = get_teacher().get_session(session_id)
    except SessionNotFound:
        raise session_not_found(session_id)

    transcript = await transcribe_student_audio(audio, session)
    return {"text": transcript}


@app.delete("/api/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    try:
        get_teacher().end_session(session_id)
    except SessionNotFound:
        raise session_not_found(session_id)

    session_viewer_sources.pop(session_id, None)
    return Response(status_code=204)


@app.post("/api/sessions/{session_id}/quiz", response_model=Quiz)
def start_quiz(session_id: str, request: QuizRequest):
    try:
        return get_teacher().start_quiz(session_id, request.mode)
    except SessionNotFound:
        raise session_not_found(session_id)
    except EventNotAllowed as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )


@app.post("/api/sessions/{session_id}/quiz/answers", response_model=QuizResult)
def submit_quiz(session_id: str, submission: QuizAnswers):
    try:
        return get_teacher().submit_quiz(session_id, submission.answers, submission.attempt)
    except SessionNotFound:
        raise session_not_found(session_id)
    except EventNotAllowed as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )


@app.post("/api/tutor-speech")
async def tutorSpeech(speech: TTR):

    audio_bytes, audio_format = (
        await generate_speech_audio(
            speech.text
        )
    )

    return Response(
        content=audio_bytes,
        media_type="audio/mpeg",
    )
