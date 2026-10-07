"""Regenerate frontend's fixed Regina lines with Fish Audio.

Run from the backend directory after setting FISH_AUDIO_API_KEY in .env:
    python generate_static_audio.py
"""

import asyncio
from pathlib import Path

from main import generate_speech_audio


STATIC_LINES = {
    "lecture-hall": {
        "welcome.mp3": (
            "[reassuring] Welcome. I am Professor Regina. Let us begin by "
            "looking carefully at today's lecture."
        ),
        "what-would-you-like-to-ask.mp3": (
            "[reassuring] Yes, go ahead. What question would you like to raise?"
        ),
        "let-me-think.mp3": "[thoughtful] Let me consider that for a moment.",
    },
    "private-tutor": {
        "welcome.mp3": (
            "[reassuring] Hi, I am Regina. We will take this one step at a time."
        ),
        "what-would-you-like-to-ask.mp3": (
            "[reassuring] Of course. What are you wondering about?"
        ),
        "let-me-think.mp3": "[thoughtful] Let me think that through for a second.",
    },
    "study-cafe": {
        "welcome.mp3": (
            "[excited] Hey, I am Regina. Let's go through this together and make "
            "it make sense."
        ),
        "what-would-you-like-to-ask.mp3": (
            "[thoughtful] Yeah, tell me what part feels confusing."
        ),
        "let-me-think.mp3": (
            "[thoughtful] Hmm, give me a second to think about that."
        ),
    },
}

OUTPUT_ROOT = Path(__file__).parent.parent / "frontend" / "public" / "audio"


async def main() -> None:
    for environment, lines in STATIC_LINES.items():
        output_dir = OUTPUT_ROOT / environment
        output_dir.mkdir(parents=True, exist_ok=True)

        for file_name, text in lines.items():
            print(f"Generating {environment}/{file_name}...")
            audio, _ = await generate_speech_audio(text)
            (output_dir / file_name).write_bytes(audio)


if __name__ == "__main__":
    asyncio.run(main())
