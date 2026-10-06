import json

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import Environment, LectureChunk, StartSessionRequest
from agent.llm import LLM
from agent.state import Mode, initial_state
from agent.summary import (
    after_back_to_lecture,
    back_to_lecture,
    can_summarize,
    fallback_summary,
    make_summary_node,
    summary_prompt,
)

LECTURE = [
    LectureChunk(slide=1, text="Pipelining sends requests without waiting."),
    LectureChunk(slide=2, text="Head-of-line blocking delays responses."),
]
OUTLINE = [
    {"title": "Pipelining", "summary": "No waiting.", "key_points": [], "source_slides": [1]},
    {"title": "Head-of-Line Blocking", "summary": "Slow blocks fast.", "key_points": [], "source_slides": [2]},
]


def make_state(environment=Environment.STUDY_ROOM, **fields):
    state = initial_state("abc", StartSessionRequest(environment=environment, lecture=LECTURE)) | {
        "outline": OUTLINE,
        "current_topic": 0,
        "segments": ["s0", "s1", "s2"],
        "question_points": [2, 3],
        "segment_index": 0,
        "mode": Mode.EXPLAINING,
    }
    return state | fields


def fake_llm(segments=None, status=200):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status)
        content = json.dumps({"segments": segments})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return LLM("key", "model", transport=httpx.MockTransport(handler)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


def test_only_the_tutor_can_summarize():
    assert can_summarize(make_state())
    assert not can_summarize(make_state(environment=Environment.LECTURE_HALL))
    assert not can_summarize(make_state(environment=Environment.CAFE))
    assert not can_summarize(make_state(mode=Mode.ENDED))


def test_prompt_has_the_whole_lecture():
    prompt = summary_prompt(LECTURE, ["Pipelining", "Head-of-Line Blocking"])
    assert "Slide 1:\nPipelining" in prompt and "Slide 2:\nHead-of-line" in prompt
    assert "entire lecture" in prompt


def test_summary_is_written_once_and_reused():
    llm, sent = fake_llm(["sum1", "sum2"])
    node = make_summary_node(llm)
    update = node(make_state(segment_index=2))

    assert update["speech"] == ["sum1", "sum2"]
    assert update["mode"] is Mode.SUMMARIZING
    assert update["topic_progress"][0]["segment_index"] == 2  # where to come back to
    assert "Regina" in sent[0]["messages"][0]["content"]

    again = node(make_state() | update)
    assert again["speech"] == ["sum1", "sum2"]
    assert len(sent) == 1  # no second LLM call


def test_summary_fallback_when_llm_fails():
    llm, _ = fake_llm(status=503)
    update = make_summary_node(llm)(make_state())
    assert update["speech"] == fallback_summary(make_state())
    assert "Pipelining: No waiting." in update["speech"][0]


def test_back_to_lecture_resumes_where_they_were():
    llm, _ = fake_llm(["sum"])
    state = make_state(segment_index=2)
    state = state | make_summary_node(llm)(state)
    state = state | back_to_lecture(state)

    assert state["speech"] == ["s2"]  # same place, not restarted
    assert state["mode"] is Mode.EXPLAINING
    assert after_back_to_lecture(state) == "wait"


def test_back_to_lecture_after_a_finished_topic_moves_on():
    llm, _ = fake_llm(["sum"])
    state = make_state(mode=Mode.FEEDBACK, segment_index=3)  # last question answered
    state = state | make_summary_node(llm)(state)
    state = state | back_to_lecture(state)
    assert after_back_to_lecture(state) == "next_topic"
