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
    finish_intro,
    go_to_topic,
    make_closing_node,
    make_repeat_node,
)
from agent.questioning import next_topic
from agent.state import Mode, initial_state

OUTLINE = [
    {"title": "Pipelining", "summary": "Requests without waiting.", "key_points": [], "source_slides": [1]},
    {"title": "Head-of-Line Blocking", "summary": "One slow response delays others.", "key_points": [], "source_slides": [1]},
    {"title": "Multiplexing", "summary": "Many streams, one connection.", "key_points": [], "source_slides": [1]},
]
QUESTION = {"question": "Why?", "expected_answer": "Because.", "explanation": "That's why."}


def make_state(environment=Environment.LECTURE_HALL, **fields):
    request = StartSessionRequest(environment=environment, lecture=[LectureChunk(slide=1, text="HTTP")])
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
    assert not can_go_to_topic(make_state(), 3)
    assert not can_go_to_topic(make_state(), -1)


def test_new_topic_is_taught_from_the_start():
    state = make_state(completed_topics=[0], pending_question=QUESTION)
    update = go_to_topic(state, 2)
    assert update["current_topic"] == 2
    assert update["segments"] == [] and update["segment_index"] == 0
    assert update["pending_question"] is None
    assert after_entering_topic(state | update) == "explain"


def test_leaving_a_topic_saves_it_and_coming_back_resumes():
    state = make_state(segment_index=1)
    away = state | go_to_topic(state, 2)
    assert away["topic_progress"][0]["segment_index"] == 1

    away = away | {"segments": ["t2-s0"], "question_points": [1], "segment_index": 0}
    back = away | go_to_topic(away, 0)
    assert back["current_topic"] == 0
    assert back["speech"] == ["s1", "s2", "s3"]
    assert back["topic_progress"][2]["segments"] == ["t2-s0"]
    assert after_entering_topic(back) == "wait"


def test_leaving_during_a_question_resumes_the_part_it_was_about():
    state = make_state(mode=Mode.AWAITING_ANSWER, segment_index=4, pending_question=QUESTION)
    away = state | go_to_topic(state, 2)
    assert away["topic_progress"][0]["segment_index"] == 1


def test_finished_topic_is_explained_again_the_same_way():
    saved = {"segments": ["s0", "s1", "s2", "s3"], "question_points": [1, 4], "segment_index": 4}
    state = make_state(current_topic=1, segments=[], completed_topics=[0], topic_progress={0: saved})
    update = go_to_topic(state, 0)
    assert update["speech"] == ["s0"]
    assert update["segment_index"] == 0


def test_clicking_the_current_topic_restarts_it():
    update = go_to_topic(make_state(segment_index=1), 0)
    assert update["speech"] == ["s0"]
    assert update["segment_index"] == 0


# --- repeat button ----------------------------------------------------------


def test_repeat_only_for_taught_topics():
    state = make_state(current_topic=1, completed_topics=[0], topic_progress={})
    assert can_repeat(state, 0)
    assert can_repeat(state, 1)
    assert not can_repeat(state, 2)
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
    assert state["topic_progress"][1]["segments"] == ["s0", "s1", "s2", "s3"]
    prompt = sent[0]["messages"][1]["content"]
    assert '"old0"' in prompt and '"s0"' not in prompt


# --- continue ---------------------------------------------------------------


def test_continue_checks():
    for mode in (Mode.INTRO, Mode.EXPLAINING, Mode.FEEDBACK, Mode.ANSWERING_STUDENT, Mode.SUMMARIZING):
        assert can_continue(make_state(mode=mode))
    for mode in (Mode.WAITING_TOPIC, Mode.AWAITING_ANSWER, Mode.AWAITING_STUDENT_QUESTION, Mode.ENDED):
        assert not can_continue(make_state(mode=mode))


def test_continue_after_intro_finishes_intro_and_waits_for_topic():
    state = make_state(mode=Mode.INTRO, current_topic=None, segments=[], speech=["Welcome"])
    assert continue_lecture(state) == {}
    assert after_continue(state) == "finish_intro"
    update = finish_intro(state)
    assert update["mode"] is Mode.WAITING_TOPIC
    assert update["current_topic"] is None
    assert update["speech"] == []


def test_continue_after_explaining_goes_to_the_question():
    state = make_state(mode=Mode.EXPLAINING, segment_index=1)
    assert continue_lecture(state) == {"segment_index": 4}
    assert after_continue(state) == "ask_question"


def test_continue_after_mid_topic_feedback_explains_the_next_part():
    state = make_state(mode=Mode.FEEDBACK, segment_index=1)
    assert continue_lecture(state) == {}
    assert after_continue(state) == "explain"


def test_continue_after_the_topics_last_feedback_marks_it_done():
    assert after_continue(make_state(mode=Mode.FEEDBACK, segment_index=4)) == "next_topic"


def test_continue_after_answering_a_raised_hand_returns_to_the_explanation():
    state = make_state(mode=Mode.ANSWERING_STUDENT, segment_index=2)
    assert continue_lecture(state) == {}
    assert after_continue(state) == "explain"


def test_after_next_topic_always_waits_for_student_selection():
    assert after_next_topic(make_state(current_topic=None, mode=Mode.WAITING_TOPIC)) == "wait"


def test_topic_completion_introduces_the_next_outline_topic():
    update = next_topic(make_state(current_topic=0, completed_topics=[]))

    assert update["mode"] is Mode.WAITING_TOPIC
    assert "Pipelining" in update["speech"][0]
    assert "Head-of-Line Blocking" in update["speech"][0]
    assert "Choose it from the outline" in update["speech"][0]


def test_last_topic_announces_the_quiz_without_a_goodbye():
    update = next_topic(make_state(current_topic=2, completed_topics=[0, 1]))

    assert update["mode"] is Mode.ENDED
    assert "quiz is next" in update["speech"][0].lower()
    assert "goodbye" not in update["speech"][0].lower()


# --- end --------------------------------------------------------------------


@pytest.mark.parametrize("environment", list(Environment))
def test_closing_prepares_for_quiz_and_names_topics_to_review(environment):
    prompt = closing_prompt(make_state(environment=environment, completed_topics=[0, 1], topics_to_improve=[1]))
    assert "quiz is next" in prompt
    assert "Do not say goodbye" in prompt
    assert "mistakes on questions about: Head-of-Line Blocking" in prompt
    assert "Don't recap" in prompt
    assert "Requests without waiting" not in prompt


def test_closing_without_mistakes_has_nothing_to_review():
    prompt = closing_prompt(make_state(completed_topics=[0, 1]))
    assert "mistakes" not in prompt and "review" not in prompt


def test_closing_ends_the_session():
    llm, sent = fake_llm("The lecture is complete. Take a moment to collect the key ideas; the quiz is next.")
    update = make_closing_node(llm)(make_state(completed_topics=[0]))

    assert update["speech"] == ["The lecture is complete. Take a moment to collect the key ideas; the quiz is next."]
    assert update["mode"] is Mode.ENDED
    assert update["current_topic"] is None
    assert "Professor Regina" in sent[0]["messages"][0]["content"]


def test_closing_fallback_when_llm_fails():
    llm, _ = fake_llm(status=503)
    state = make_state(completed_topics=[0], topics_to_improve=[0])
    update = make_closing_node(llm)(state)
    assert update["speech"] == ["You have reached the end of the lecture. It's worth reviewing Pipelining. Take a moment to collect the key ideas; the quiz is next."]
    assert update["mode"] is Mode.ENDED
    assert fallback_closing(make_state()) == "You have reached the end of the lecture. Take a moment to collect the key ideas; the quiz is next."
