import asyncio
import base64
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from agent.contract import LectureChunk
from fastapi import FastAPI, File, HTTPException, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")

app = FastAPI()

origins = ["http://localhost:5173"]

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


# ---------------------------------------------------------
# TEXT-TO-SPEECH
# ---------------------------------------------------------

async def generate_speech_audio(text: str):
    api_key = (
        os.getenv("FEATHERLESS_API_KEY")
        or os.getenv("API_KEY")
    )

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="Missing Featherless API key.",
        )

    url = "https://api.featherless.ai/v1/audio/speech"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "hexgrad/Kokoro-82M",
        "input": text,
        "voice": "af_bella",

        # We request WAV, but Featherless can still return
        # the model's actual native format.
        "response_format": "wav",

        # IMPORTANT:
        # Ask Featherless for a self-describing JSON response
        # instead of ambiguous raw binary.
        "delivery": "json",
    }

    async with httpx.AsyncClient(
        timeout=60.0
    ) as client:

        response = await client.post(
            url,
            headers=headers,
            json=payload,
        )

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"TTS failed: {response.text}",
        )

    try:
        data = response.json()
    except ValueError:
        raise HTTPException(
            status_code=502,
            detail="Featherless returned an invalid TTS response.",
        )

    audio_base64 = data.get("audio")
    audio_format = data.get("format")

    if not audio_base64:
        raise HTTPException(
            status_code=502,
            detail="Featherless returned no audio data.",
        )

    try:
        audio_bytes = base64.b64decode(audio_base64)
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Could not decode Featherless audio.",
        )

    if len(audio_bytes) == 0:
        raise HTTPException(
            status_code=502,
            detail="Featherless returned empty audio.",
        )

    print("TTS format:", audio_format)
    print("TTS audio bytes:", len(audio_bytes))
    print("TTS first bytes:", audio_bytes[:12])

    return audio_bytes, audio_format


@app.get('/')
def main():
    return {"message": "hello world"}


@app.post("/api/upload-pdf")
async def upload_pdf(
    pdf: UploadFile = File(...)
):
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

    lecture_chunks = await pages_to_lecture_chunks(
        pages
    )

    ## invoke lecture chunks into the agent's workflow and return current speach

    lecture_chunks = await pages_to_lecture_chunks(
        pages
    )

    return PdfUploadResponse(
        lecture_chunks=lecture_chunks
    )


@app.post("/api/tutor-speech")
async def tutorSpeech(speech: TTR):

    audio_bytes, audio_format = (
        await generate_speech_audio(
            speech.text
        )
    )

    media_types = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
        "pcm": "audio/L16",
    }

    media_type = media_types.get(
        audio_format,
        "application/octet-stream",
    )

    return Response(
        content=audio_bytes,
        media_type=media_type,
    )