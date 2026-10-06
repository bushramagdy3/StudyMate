"""How the teacher agent talks to the LLM on Featherless.

Every LLM call in the agent goes through this file, so the API key, model,
retries and reply cleanup live in one place.

Two kinds of calls:
- llm.chat(...)       -> plain text, e.g. what the teacher says
- llm.chat_json(...)  -> structured data checked against a pydantic model,
                         e.g. the lecture outline or an answer evaluation

Quick check that your key and model work (from the backend folder):
    python -m agent.llm
"""

import json
import os
import re
import time
from pathlib import Path
from typing import TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

FEATHERLESS_URL = "https://api.featherless.ai/v1/chat/completions"
DEFAULT_MODEL = "moonshotai/Kimi-K3"

# Errors worth retrying: rate/concurrency limit and temporary server problems.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
RETRY_DELAY = 2  # seconds; doubles after each failed attempt

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """The LLM call failed, or its reply couldn't be used."""


class LLM:
    def __init__(
        self,
        api_key: str,
        model: str,
        transport: httpx.BaseTransport | None = None,  # lets tests fake Featherless
    ):
        self.model = model
        self._client = httpx.Client(
            timeout=120,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        """Send a conversation and return the model's reply as plain text."""
        payload = {"model": self.model, "messages": messages, "temperature": temperature}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self._client.post(FEATHERLESS_URL, json=payload)
            except httpx.HTTPError:
                response = None  # timeout or connection problem: retry

            if response is not None and response.status_code == 200:
                text = _reply_text(response)
                if text:
                    return text

            elif response is not None and response.status_code not in RETRYABLE_STATUS:
                # Wrong key, unknown model, bad request: retrying won't help.
                raise LLMError(f"Featherless error for model {self.model}: {_error_message(response)}")

            if attempt < MAX_ATTEMPTS - 1:
                time.sleep(RETRY_DELAY * 2**attempt)

        raise LLMError(f"No usable reply from {self.model} after {MAX_ATTEMPTS} attempts.")

    def chat_json(self, messages: list[dict], schema: type[T], temperature: float = 0.3) -> T:
        """Ask for JSON matching `schema` (a pydantic model) and return it validated.

        If the reply isn't valid, the model is shown its mistake and asked
        once more. If it fails again, LLMError is raised so the caller can
        use a fallback.
        """
        messages = [*messages, {"role": "user", "content": _json_instructions(schema)}]

        for attempt in range(2):
            reply = self.chat(messages, temperature=temperature)
            try:
                return schema.model_validate(json.loads(_extract_json(reply)))
            except (ValueError, ValidationError) as error:
                if attempt == 1:
                    raise LLMError(f"Invalid JSON from {self.model}: {error}") from error
                messages = [
                    *messages,
                    {"role": "assistant", "content": reply},
                    {
                        "role": "user",
                        "content": f"That reply was not valid: {error}\n"
                        "Reply again with ONLY the corrected JSON object.",
                    },
                ]

        raise AssertionError("unreachable")


def messages(system: str, user: str) -> list[dict]:
    """The usual two-message conversation: instructions + the task."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def get_llm() -> LLM:
    """The teacher's LLM, configured from backend/.env."""
    load_dotenv(Path(__file__).parent.parent / ".env")
    api_key = os.getenv("FEATHERLESS_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise LLMError("Missing FEATHERLESS_API_KEY in backend/.env")
    # The teacher can use a different model from the PDF upload; by default it's the same one.
    model = (
        os.getenv("FEATHERLESS_TEACHER_MODEL")
        or os.getenv("FEATHERLESS_MODEL")
        or DEFAULT_MODEL
    )
    return LLM(api_key, model)


# ---------------------------------------------------------------------------
# Reply cleanup
# ---------------------------------------------------------------------------


def _reply_text(response: httpx.Response) -> str:
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""
    # Some models "think out loud" in <think>...</think> before answering; drop that.
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL)
    return content.strip()


def _error_message(response: httpx.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except Exception:
        return response.text


def _extract_json(reply: str) -> str:
    """Pull the JSON object out of a reply that may wrap it in ```json fences or chatter."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", reply, flags=re.DOTALL)
    if fenced:
        reply = fenced.group(1)
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object found in the reply")
    return reply[start : end + 1]


def _json_instructions(schema: type[BaseModel]) -> str:
    return (
        "Reply with ONLY a JSON object, with no other text and no code fences. "
        "It must match this JSON schema:\n"
        + json.dumps(schema.model_json_schema(), indent=2)
    )


if __name__ == "__main__":
    # Real call to Featherless: checks your key, model and connection.
    from agent.contract import Environment
    from agent.personalities import build_system_prompt, get_personality

    class Check(BaseModel):
        topic: str
        one_sentence_summary: str

    llm = get_llm()
    system = build_system_prompt(get_personality(Environment.STUDY_ROOM))
    print(f"Model: {llm.model}\n")
    print("Text reply:")
    print(llm.chat(messages(system, "Greet the student and say we'll learn about HTTP today.")))
    print("\nJSON reply:")
    print(llm.chat_json(messages(system, "Summarise what HTTP is."), Check))
