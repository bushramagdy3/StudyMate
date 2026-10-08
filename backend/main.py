import asyncio
import base64
import os
from dataclasses import dataclass
from pathlib import Path

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
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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


class TTR(BaseModel):
    text: str


teacher: Teacher | None = None


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


async def process_pdf_upload(pdf: UploadFile) -> list[LectureChunk]:
    if pdf.content_type != "application/pdf":
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF file.",
        )

    pdf_bytes = await pdf.read()

    if len(pdf_bytes) == 0:
        raise HTTPException(
            status_code=400,
            detail="PDF file is empty.",
        )

    try:
        # Rendering pages is slow CPU work; a thread keeps the server responsive.
        pages = await asyncio.to_thread(
            read_pages,
            pdf_bytes,
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Could not read PDF file.",
        )

    return await pages_to_lecture_chunks(
        pages
    )


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


@app.post("/api/upload-pdf")
async def upload_pdf(
    pdf: UploadFile = File(...)
):
    return PdfUploadResponse(
        lecture_chunks=await process_pdf_upload(pdf)
    )


@app.post("/api/sessions", response_model=TeacherResponse)
async def start_session(
    pdf: UploadFile = File(...),
    environment: str | None = Form(None),
    enviroment: str | None = Form(None),
):
    request = StartSessionRequest(
        environment=parse_environment(environment or enviroment),
        lecture=await process_pdf_upload(pdf),
    )

    try:
        return get_teacher().start_session(request)
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
        return get_teacher().submit_quiz(session_id, submission.answers)
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
