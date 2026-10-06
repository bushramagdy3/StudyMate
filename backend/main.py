import base64
import os
from pathlib import Path

import httpx
from agent.contract import LectureChunk
from fastapi import FastAPI, File, HTTPException, UploadFile
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv(Path(__file__).parent / ".env")

app = FastAPI()


class PdfUploadResponse(BaseModel):
    lecture_chunks: list[LectureChunk]


def pdf_to_page_images(pdf_bytes: bytes) -> list[bytes]:
    import pymupdf

    images = []
    pdf_document = pymupdf.open(stream=pdf_bytes, filetype="pdf")

    for page in pdf_document:
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        image_bytes = pixmap.tobytes("png")
        images.append(image_bytes)

    pdf_document.close()
    return images


def describe_page_image(image_bytes: bytes, slide_number: int) -> str:
    api_key = os.getenv("FEATHERLESS_API_KEY") or os.getenv("API_KEY")
    model = os.getenv("FEATHERLESS_MODEL", "google/gemma-3-27b-it")

    if not api_key:
        raise HTTPException(status_code=500, detail="Missing Featherless API key.")

    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt = f"""
Look at this lecture slide/page as an image.

Describe precisely what slide {slide_number} is about.
Describe the visible topic, diagrams, images, tables, labels, examples,
relationships, and the scope of the content on the page.

Return only the description text.
Do not return JSON.
Do not add extra fields.
"""

    response = httpx.post(
        "https://api.featherless.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}",
                            },
                        },
                    ],
                }
            ],
            "temperature": 0.1,
        },
        timeout=120,
    )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=response.text)

    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def images_to_lecture_chunks(page_images: list[bytes]) -> list[LectureChunk]:
    lecture_chunks = []

    for index, image_bytes in enumerate(page_images, start=1):
        description = describe_page_image(image_bytes, index)
        lecture_chunk = LectureChunk(slide=index, text=description)
        lecture_chunks.append(lecture_chunk)

    return lecture_chunks


@app.get('/')
def main():
    return {"message" : "hello world"}


@app.post("/api/upload-pdf")
async def upload_pdf(pdf: UploadFile = File(...)):
    if pdf.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Upload a PDF file.")

    pdf_bytes = await pdf.read()

    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="PDF file is empty.")

    try:
        page_images = pdf_to_page_images(pdf_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not read PDF file.")

    lecture_chunks = images_to_lecture_chunks(page_images)

    return PdfUploadResponse(lecture_chunks=lecture_chunks)
