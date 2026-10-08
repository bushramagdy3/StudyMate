import asyncio
from io import BytesIO

import httpx
from fastapi import UploadFile

from agent.contract import AvatarState, Awaiting, TeacherResponse, Topic
import main


def run(coroutine):
    return asyncio.run(coroutine)


def session_response():
    return TeacherResponse(
        session_id="session-1",
        speech=[],
        avatar_state=AvatarState.IDLE,
        awaiting=Awaiting.ANSWER,
        outline=[Topic(index=0, title="HTTP request response model")],
    )


def recording():
    return UploadFile(
        file=BytesIO(b"webm-bytes"),
        filename="answer.webm",
        headers={"content-type": "audio/webm"},
    )


def test_groq_transcription_uses_audio_file_and_lecture_context(monkeypatch):
    monkeypatch.setenv("GROQ_STT_API_KEY", "groq-test-key")
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = request.content.decode("latin-1")
        return httpx.Response(200, json={"text": "It uses a GET request."})

    transcript = run(
        main.transcribe_student_audio(
            recording(),
            session_response(),
            transport=httpx.MockTransport(handler),
        )
    )

    assert transcript == "It uses a GET request."
    assert captured["url"] == main.GROQ_STT_URL
    assert captured["authorization"] == "Bearer groq-test-key"
    assert 'name="model"' in captured["body"]
    assert main.GROQ_STT_MODEL in captured["body"]
    assert "HTTP request response model" in captured["body"]
    assert 'name="file"; filename="answer.webm"' in captured["body"]


def test_groq_rate_limit_has_machine_readable_voice_limit_code(monkeypatch):
    monkeypatch.setenv("GROQ_STT_API_KEY", "groq-test-key")

    async def transcribe():
        return await main.transcribe_student_audio(
            recording(),
            session_response(),
            transport=httpx.MockTransport(lambda request: httpx.Response(429)),
        )

    try:
        run(transcribe())
    except main.HTTPException as error:
        assert error.status_code == 429
        assert error.detail["code"] == "voice_limit_reached"
    else:
        raise AssertionError("Expected a free-tier limit error")
