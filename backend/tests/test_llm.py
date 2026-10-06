import json

import httpx
import pytest
from pydantic import BaseModel

from agent import llm as llm_module
from agent.llm import LLM, LLMError, get_llm, messages


class Topic(BaseModel):
    title: str
    key_points: list[str]


def reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def fake_llm(*responses: httpx.Response) -> tuple[LLM, list[dict]]:
    """An LLM whose Featherless returns the given responses in order. Also returns the requests sent."""
    queue = iter(responses)
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return next(queue)

    return LLM("test-key", "test-model", transport=httpx.MockTransport(handler)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


def test_chat_returns_text_and_sends_model_and_messages():
    llm, sent = fake_llm(reply("  Hello there!  "))
    assert llm.chat(messages("You are a tutor.", "Say hi")) == "Hello there!"
    assert sent[0]["model"] == "test-model"
    assert sent[0]["messages"][0] == {"role": "system", "content": "You are a tutor."}


def test_chat_removes_thinking():
    llm, _ = fake_llm(reply("<think>let me plan this</think>\nHello!"))
    assert llm.chat(messages("s", "u")) == "Hello!"


def test_chat_retries_rate_limits_and_server_errors():
    llm, sent = fake_llm(httpx.Response(429), httpx.Response(503), reply("finally"))
    assert llm.chat(messages("s", "u")) == "finally"
    assert len(sent) == 3


def test_chat_retries_empty_replies():
    llm, _ = fake_llm(reply(""), reply("there we go"))
    assert llm.chat(messages("s", "u")) == "there we go"


def test_chat_gives_up_after_max_attempts():
    llm, sent = fake_llm(*[httpx.Response(503)] * llm_module.MAX_ATTEMPTS)
    with pytest.raises(LLMError):
        llm.chat(messages("s", "u"))
    assert len(sent) == llm_module.MAX_ATTEMPTS


def test_chat_fails_fast_on_wrong_key():
    llm, sent = fake_llm(httpx.Response(401, json={"error": {"message": "invalid key"}}))
    with pytest.raises(LLMError, match="invalid key"):
        llm.chat(messages("s", "u"))
    assert len(sent) == 1


@pytest.mark.parametrize(
    "text",
    [
        '{"title": "HTTP/2", "key_points": ["multiplexing"]}',
        '```json\n{"title": "HTTP/2", "key_points": ["multiplexing"]}\n```',
        'Sure! Here it is:\n{"title": "HTTP/2", "key_points": ["multiplexing"]}\nHope that helps.',
    ],
)
def test_chat_json_parses_common_reply_shapes(text):
    llm, sent = fake_llm(reply(text))
    topic = llm.chat_json(messages("s", "Plan a topic"), Topic)
    assert topic == Topic(title="HTTP/2", key_points=["multiplexing"])
    assert "JSON schema" in sent[0]["messages"][-1]["content"]


def test_chat_json_asks_again_after_a_bad_reply():
    llm, sent = fake_llm(
        reply('{"title": "HTTP/2"}'),  # missing key_points
        reply('{"title": "HTTP/2", "key_points": ["multiplexing"]}'),
    )
    assert llm.chat_json(messages("s", "u"), Topic).key_points == ["multiplexing"]
    retry_messages = sent[1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "not valid" in retry_messages[-1]["content"]


def test_chat_json_raises_after_two_bad_replies():
    llm, _ = fake_llm(reply("no json here"), reply("still none"))
    with pytest.raises(LLMError, match="Invalid JSON"):
        llm.chat_json(messages("s", "u"), Topic)


def test_get_llm_reads_settings(monkeypatch):
    monkeypatch.setattr(llm_module, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("FEATHERLESS_API_KEY", "key")
    monkeypatch.setenv("FEATHERLESS_MODEL", "my-model")
    assert get_llm().model == "my-model"

    monkeypatch.delenv("FEATHERLESS_MODEL")
    assert get_llm().model == llm_module.DEFAULT_MODEL


def test_get_llm_needs_a_key(monkeypatch):
    monkeypatch.setattr(llm_module, "load_dotenv", lambda *args: None)
    monkeypatch.delenv("FEATHERLESS_API_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    with pytest.raises(LLMError, match="FEATHERLESS_API_KEY"):
        get_llm()
