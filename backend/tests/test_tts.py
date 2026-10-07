import asyncio
import json

import httpx

import main


def run(coroutine):
    return asyncio.run(coroutine)


def test_fish_tts_uses_katkat_s21_pro_free_and_returns_mp3(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fish-test-key")
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3fish-mp3")

    audio, audio_format = run(
        main.generate_speech_audio(
            "[reassuring] Hello there.",
            transport=httpx.MockTransport(handler),
        )
    )

    assert captured["url"] == main.FISH_TTS_URL
    assert captured["headers"]["authorization"] == "Bearer fish-test-key"
    assert captured["headers"]["model"] == main.FISH_MODEL
    assert captured["payload"] == {
        "text": "[reassuring] Hello there.",
        "reference_id": main.FISH_VOICE_ID,
        "format": "mp3",
        "normalize": True,
        "latency": "balanced",
    }
    assert audio == b"ID3fish-mp3"
    assert audio_format == "mp3"


def test_fish_tts_rejects_empty_audio(monkeypatch):
    monkeypatch.setenv("FISH_AUDIO_API_KEY", "fish-test-key")

    async def generate():
        return await main.generate_speech_audio(
            "Hello.",
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )

    try:
        run(generate())
    except main.HTTPException as error:
        assert error.status_code == 502
        assert "empty" in error.detail.lower()
    else:
        raise AssertionError("Expected an HTTPException for empty Fish audio")
