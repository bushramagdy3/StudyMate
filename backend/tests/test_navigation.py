import json

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import Environment, LectureChunk, StartSessionRequest
from agent.llm import LLM
from agent.navigation import (
    after_continue,
    after_entering_topic,
    after_next_topic,
    can_continue,
    can_go_to_topic,
    can_repeat,
    choose_topic_to_repeat,
    closing_prompt,
    continue_lecture,
    fallback_closing,
    go_to_topic,
    make_closing_node,
    make_repeat_node,
)
from agent.state import Mode, initial_state

OUTLINE = [
    {"title": "Pipelining", "summary": "Requests without waiting.", "key_points": [], "source_slides": [1]},
    {"title": "Head-of-Line Blocking", "summary": "One slow response delays others.", "key_points": [], "source_slides": [1]},
    {"title": "Multiplexing", "summary": "Many streams, one connection.", "key_points": [], "source_slides": [1]},
]
QUESTION = {"question": "Why?", "expected_answer": "Because.", "explanation": "That's why."}


def make_state(**fields):
    request = StartSessionRequest(environment=Environment.LECTURE_HALL, lecture=[LectureChunk(slide=1, text="HTTP")])
    state = initial_state("abc", request) | {
        "outline": OUTLINE,
        "current_topic": 0,
        "segments": ["s0", "s1", "s2", "s3"],
        "question_points": [1, 4],
        "segment_index": 1,
        "mode": Mode.EXPLAINING,
    }
    return state | fields


def fake_llm(content=None, status=200):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status)
        text = content if isinstance(content, str) else json.dumps(content)
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return LLM("key", "model", transport=httpx.MockTransport(handler)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


# --- clicking a topic's name -------------------------------------------------


def test_topic_can_be_clicked_any_time_during_the_lecture():
    for mode in Mode:
        assert can_go_to_topic(make_state(mode=mode), 2) is (mode is not Mode.ENDED)
    assert not can_go_to_topic(make_state(), 3)  # no such topic
    assert not can_go_to_topic(make_state(), -1)


def test_new_topic_is_taught_from_the_start():
    state = make_state(completed_topics=[0], pending_question=QUESTION)
    update = go_to_topic(state, 2)
    assert update["current_topic"] == 2
    assert update["segments"] == [] and update["segment_index"] == 0  # explain node writes it
    assert update["pending_question"] is None
    assert after_entering_topic(state | update) == "explain"


def test_leaving_a_topic_saves_it_and_coming_back_resumes():
    state = make_state(segment_index=1)  # in topic 0, part [s1, s2, s3] playing
    away = state | go_to_topic(state, 2)
    assert away["topic_progress"][0]["segment_index"] == 1

    away = away | {"segments": ["t2-s0"], "question_points": [1], "segment_index": 0}
    back = away | go_to_topic(away, 0)
    assert back["current_topic"] == 0
    assert back["speech"] == ["s1", "s2", "s3"]  # resumed where they left
    assert back["topic_progress"][2]["segments"] == ["t2-s0"]  # topic 2 saved too
    assert after_entering_topic(back) == "wait"  # already set up, no LLM call


def test_leaving_during_a_question_resumes_the_part_it_was_about():
    state = make_state(mode=Mode.AWAITING_ANSWER, segment_index=4, pending_question=QUESTION)
    away = state | go_to_topic(state, 2)
    assert away["topic_progress"][0]["segment_index"] == 1  # start of part [s1, s2, s3]


def test_finished_topic_is_explained_again_the_same_way():
    saved = {"segments": ["s0", "s1", "s2", "s3"], "question_points": [1, 4], "segment_index": 4}
    state = make_state(current_topic=1, segments=[], completed_topics=[0], topic_progress={0: saved})
    update = go_to_topic(state, 0)
    assert update["speech"] == ["s0"]  # same explanation, from the start
    assert update["segment_index"] == 0


def test_clicking_the_current_topic_restarts_it():
    update = go_to_topic(make_state(segment_index=1), 0)
    assert update["speech"] == ["s0"]
    assert update["segment_index"] == 0


# --- repeat button ----------------------------------------------------------


def test_repeat_only_for_taught_topics():
    state = make_state(current_topic=1, completed_topics=[0], topic_progress={})
    assert can_repeat(state, 0)  # finished
    assert can_repeat(state, 1)  # current
    assert not can_repeat(state, 2)  # not taught yet
    assert not can_repeat(make_state(mode=Mode.ENDED), 0)


def test_repeat_the_current_topic_reprompts_with_the_old_explanation():
    llm, sent = fake_llm({"segments": ["n0", "n1", "n2", "n3"], "question_after": [2, 4]})
    state = make_state(mode=Mode.AWAITING_ANSWER, pending_question=QUESTION, attempts=1)
    state = state | choose_topic_to_repeat(state, 0)
    update = make_repeat_node(llm)(state)

    assert update["segments"] == ["n0", "n1", "n2", "n3"]
    assert update["speech"] == ["n0", "n1"]
    assert update["mode"] is Mode.EXPLAINING
    assert update["pending_question"] is None and update["attempts"] == 0
    prompt = sent[0]["messages"][1]["content"]
    assert '"s0"' in prompt and "differently" in prompt


def test_repeat_a_finished_topic_uses_its_saved_explanation():
    llm, sent = fake_llm({"segments": ["n0", "n1", "n2", "n3"], "question_after": [2, 4]})
    saved = {"segments": ["old0", "old1"], "question_points": [2], "segment_index": 2}
    state = make_state(current_topic=1, completed_topics=[0], topic_progress={0: saved})
    state = state | choose_topic_to_repeat(state, 0)
    make_repeat_node(llm)(state)

    assert state["current_topic"] == 0
    assert state["topic_progress"][1]["segments"] == ["s0", "s1", "s2", "s3"]  # topic 1 saved
    prompt = sent[0]["messages"][1]["content"]
    assert '"old0"' in prompt and '"s0"' not in prompt


# --- continue ---------------------------------------------------------------


def test_continue_checks():
    for mode in (Mode.EXPLAINING, Mode.FEEDBACK, Mode.ANSWERING_STUDENT):
        assert can_continue(make_state(mode=mode))
    for mode in (Mode.AWAITING_ANSWER, Mode.AWAITING_STUDENT_QUESTION, Mode.ENDED):
        assert not can_continue(make_state(mode=mode))


def test_continue_after_explaining_goes_to_the_question():
    state = make_state(mode=Mode.EXPLAINING, segment_index=1)  # part [s1, s2, s3]
    assert continue_lecture(state) == {"segment_index": 4}
    assert after_continue(state) == "ask_question"


def test_continue_after_mid_topic_feedback_explains_the_next_part():
    state = make_state(mode=Mode.FEEDBACK, segment_index=1)
    assert continue_lecture(state) == {}
    assert after_continue(state) == "explain"


def test_continue_after_the_topics_last_feedback_moves_to_the_next_topic():
    assert after_continue(make_state(mode=Mode.FEEDBACK, segment_index=4)) == "next_topic"


def test_continue_after_answering_a_raised_hand_returns_to_the_explanation():
    state = make_state(mode=Mode.ANSWERING_STUDENT, segment_index=2)
    assert continue_lecture(state) == {}
    assert after_continue(state) == "explain"


def test_after_next_topic():
    assert after_next_topic(make_state(current_topic=1, segments=[])) == "explain"
    assert after_next_topic(make_state(current_topic=1)) == "wait"  # resumed a saved topic
    assert after_next_topic(make_state(current_topic=None)) == "closing"


# --- end --------------------------------------------------------------------


def test_closing_prompt_summarises_progress():
    state = make_state(
        completed_topics=[0, 1],
        performance={0: {"correct": 2, "incorrect": 0}, 1: {"correct": 1, "incorrect": 1}},
    )
    prompt = closing_prompt(state)
    assert "- Pipelining: Requests without waiting." in prompt
    assert "not covered yet: Multiplexing" in prompt
    assert "well on: Pipelining" in prompt
    assert "harder: Head-of-Line Blocking" in prompt


def test_closing_ends_the_session():
    llm, sent = fake_llm("Great session today! Goodbye.")
    update = make_closing_node(llm)(make_state(completed_topics=[0]))

    assert update["speech"] == ["Great session today! Goodbye."]
    assert update["mode"] is Mode.ENDED
    assert update["current_topic"] is None
    assert "Professor Regina" in sent[0]["messages"][0]["content"]


def test_closing_fallback_when_llm_fails():
    llm, _ = fake_llm(status=503)
    state = make_state(completed_topics=[0], performance={0: {"correct": 0, "incorrect": 1}})
    update = make_closing_node(llm)(state)
    assert update["speech"] == [fallback_closing(state)]
    assert "We covered Pipelining" in update["speech"][0]
    assert "reviewing Pipelining" in update["speech"][0]
    assert update["mode"] is Mode.ENDED
