import json

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import Environment, LectureChunk, StartSessionRequest
from agent.hand_raise import (
    HAND_RAISE_REPLIES,
    make_answer_student_question_node,
    raise_hand,
    student_question_prompt,
)
from agent.llm import LLM
from agent.state import Mode, initial_state, to_response

LECTURE = [
    LectureChunk(slide=1, text="HTTP/1.1 pipelining sends requests without waiting."),
    LectureChunk(slide=2, text="HTTP/2 multiplexing uses streams."),
]
OUTLINE = [
    {"title": "Pipelining", "summary": "", "key_points": [], "source_slides": [1]},
    {"title": "Multiplexing", "summary": "", "key_points": [], "source_slides": [2]},
]
def make_state(environment=Environment.STUDY_ROOM, **fields):
    request = StartSessionRequest(environment=environment, lecture=LECTURE)
    state = initial_state("abc", request) | {
        "outline": OUTLINE,
        "current_topic": 0,
        "segments": ["s0", "s1", "s2", "s3"],
        "question_points": [1, 4],  # parts: [s0] and [s1, s2, s3]
        "segment_index": 1,  # the part [s1, s2, s3] is playing
        "mode": Mode.EXPLAINING,
    }
    return state | fields


def fake_llm(text=None, status=200):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return LLM("key", "model", transport=httpx.MockTransport(handler)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


# --- raising a hand ---------------------------------------------------------


def test_hand_raised_during_explanation_remembers_the_segment():
    update = raise_hand(make_state(), segment_index=2)  # 3rd item of [s1, s2, s3] = s3

    assert update["mode"] is Mode.AWAITING_STUDENT_QUESTION
    assert update["segment_index"] == 3
    assert update["speech"] == [HAND_RAISE_REPLIES["tutor"]]


def test_segment_index_is_kept_inside_the_playing_part():
    assert raise_hand(make_state(), segment_index=9)["segment_index"] == 3
    assert raise_hand(make_state(segment_index=0), segment_index=5)["segment_index"] == 0


@pytest.mark.parametrize(
    "mode",
    [
        Mode.FEEDBACK,
        Mode.AWAITING_ANSWER,
        Mode.AWAITING_STUDENT_QUESTION,
        Mode.ANSWERING_STUDENT,
        Mode.ENDED,
    ],
)
def test_hand_can_only_be_raised_while_explaining(mode):
    assert raise_hand(make_state(mode=mode), segment_index=0) == {}


def test_frontend_is_told_when_a_hand_can_be_raised():
    assert to_response(make_state(mode=Mode.EXPLAINING)).can_raise_hand
    for mode in Mode:
        if mode is not Mode.EXPLAINING:
            assert not to_response(make_state(mode=mode)).can_raise_hand


def test_each_personality_has_its_own_reply():
    reply = raise_hand(make_state(environment=Environment.CAFE), 0)["speech"]
    assert reply == [HAND_RAISE_REPLIES["study friend"]]


# --- answering the student's question ---------------------------------------


def asking_state(**fields):
    defaults = {
        "mode": Mode.AWAITING_STUDENT_QUESTION,
        "student_input": "Is pipelining used today?",
    }
    return make_state(**(defaults | fields))


def test_prompt_has_the_question_slides_and_lecture_topics():
    prompt = student_question_prompt(asking_state(), "Is pipelining used today?")
    assert '"Is pipelining used today?"' in prompt
    assert "Slide 1:\nHTTP/1.1 pipelining" in prompt
    assert "Pipelining, Multiplexing" in prompt
    assert "back to where we were" in prompt


def test_answer_then_back_to_the_explanation():
    llm, sent = fake_llm("Rarely, browsers turned it off. Okay, back to where we were.")
    update = make_answer_student_question_node(llm)(asking_state())

    assert update["speech"] == ["Rarely, browsers turned it off. Okay, back to where we were."]
    assert update["mode"] is Mode.ANSWERING_STUDENT
    assert update["history"] == [
        {"role": "student", "text": "Is pipelining used today?"},
        {"role": "teacher", "text": "Rarely, browsers turned it off. Okay, back to where we were."},
    ]
    assert "Regina" in sent[0]["messages"][0]["content"]


def test_llm_failure_still_lets_the_lecture_continue():
    llm, _ = fake_llm(status=503)
    update = make_answer_student_question_node(llm)(asking_state())
    assert update["speech"][0].startswith("Good question!")
    assert update["mode"] is Mode.ANSWERING_STUDENT
