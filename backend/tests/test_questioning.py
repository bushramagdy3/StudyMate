import json

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import Environment, LectureChunk, StartSessionRequest
from agent.llm import LLM
from agent.questioning import (
    ask_prompt,
    fallback_question,
    feedback_prompt,
    make_ask_question_node,
    make_evaluate_answer_node,
    next_topic,
    part_just_explained,
    mark_to_improve,
    topic_finished,
)
from agent.state import Mode, initial_state

OUTLINE = [
    {
        "title": "Pipelining",
        "summary": "Sending requests without waiting.",
        "key_points": ["several requests at once"],
        "source_slides": [1],
    },
    {
        "title": "Head-of-Line Blocking",
        "summary": "One slow response delays the rest.",
        "key_points": [],
        "source_slides": [1],
    },
]

QUESTION = {
    "question": "Why can pipelining be faster?",
    "expected_answer": "It doesn't wait for each response before sending the next request.",
    "explanation": "Requests overlap, so less time is spent waiting.",
}


def make_state(**fields):
    request = StartSessionRequest(
        environment=Environment.STUDY_ROOM,
        lecture=[LectureChunk(slide=1, text="HTTP")],
    )
    state = initial_state("abc", request) | {
        "outline": OUTLINE,
        "current_topic": 0,
        "segments": ["s0", "s1", "s2", "s3"],
        "question_points": [1, 4],
        "segment_index": 1,
    }
    return state | fields


def fake_llm(reply=None, status=200):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}]})

    return LLM("key", "model", transport=httpx.MockTransport(handler)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


# --- asking -----------------------------------------------------------------


def test_part_just_explained():
    assert part_just_explained(make_state(segment_index=1)) == ["s0"]
    assert part_just_explained(make_state(segment_index=4)) == ["s1", "s2", "s3"]


def test_question_is_about_the_part_just_explained():
    prompt = ask_prompt(make_state(segment_index=4))
    assert '"s1 s2 s3"' in prompt
    assert '"s0' not in prompt


def test_ask_question_node():
    llm, sent = fake_llm(QUESTION)
    update = make_ask_question_node(llm)(make_state())

    assert update["pending_question"] == QUESTION
    assert update["speech"] == [QUESTION["question"]]
    assert update["mode"] is Mode.AWAITING_ANSWER
    assert update["attempts"] == 0
    assert "Regina" in sent[0]["messages"][0]["content"]  # personality is used


def test_ask_question_falls_back_when_llm_fails():
    llm, _ = fake_llm(status=503)
    update = make_ask_question_node(llm)(make_state())
    assert update["pending_question"] == fallback_question(OUTLINE[0])
    assert "Pipelining" in update["speech"][0]


# --- grading and responding -------------------------------------------------


def answering_state(attempts=0, answer="it doesn't wait"):
    return make_state(
        pending_question=QUESTION,
        attempts=attempts,
        student_input=answer,
        mode=Mode.AWAITING_ANSWER,
    )


def test_prompt_first_try_asks_for_a_hint_if_wrong():
    prompt = feedback_prompt(answering_state(attempts=0), "no idea")
    assert 'The student answered: "no idea"' in prompt
    assert "Do NOT give the answer away" in prompt


def test_prompt_last_try_asks_to_reveal_if_wrong():
    prompt = feedback_prompt(answering_state(attempts=1), "no idea")
    assert "last try" in prompt
    assert "give the correct answer" in prompt


def test_correct_first_try_praises_and_continues():
    llm, _ = fake_llm({"correct": True, "response": "Yes! Requests overlap."})
    update = make_evaluate_answer_node(llm)(answering_state(attempts=0))

    assert update["speech"] == ["Yes! Requests overlap."]
    assert update["mode"] is Mode.FEEDBACK
    assert update["pending_question"] is None
    assert "topics_to_improve" not in update  # no mistake
    assert update["history"] == [
        {"role": "student", "text": "it doesn't wait"},
        {"role": "teacher", "text": "Yes! Requests overlap."},
    ]


def test_wrong_first_try_gives_a_hint_and_waits_again():
    llm, _ = fake_llm({"correct": False, "response": "Close! Think about waiting."})
    update = make_evaluate_answer_node(llm)(answering_state(attempts=0, answer="it's faster"))

    assert update["speech"] == ["Close! Think about waiting."]
    assert update["mode"] is Mode.AWAITING_ANSWER
    assert update["attempts"] == 1
    assert "pending_question" not in update  # same question stays
    assert update["topics_to_improve"] == [0]  # a mistake, even if they get it right next


def test_correct_on_retry_praises():
    llm, _ = fake_llm({"correct": True, "response": "There you go!"})
    state = answering_state(attempts=1) | {"topics_to_improve": [0]}  # wrong the first time
    update = make_evaluate_answer_node(llm)(state)
    assert update["mode"] is Mode.FEEDBACK
    assert "topics_to_improve" not in update  # stays on the list


def test_wrong_on_last_try_reveals_and_continues():
    llm, _ = fake_llm({"correct": False, "response": "The answer is that it doesn't wait."})
    update = make_evaluate_answer_node(llm)(answering_state(attempts=1, answer="no idea"))

    assert update["speech"] == ["The answer is that it doesn't wait."]
    assert update["mode"] is Mode.FEEDBACK
    assert update["pending_question"] is None
    assert update["topics_to_improve"] == [0]


def test_empty_llm_response_uses_fallback_text():
    llm, _ = fake_llm({"correct": False, "response": ""})
    update = make_evaluate_answer_node(llm)(answering_state(attempts=1))
    assert update["speech"][0].startswith("Not quite. The answer is:")


def test_grading_failure_gives_answer_without_scoring():
    llm, _ = fake_llm(status=503)
    update = make_evaluate_answer_node(llm)(answering_state())

    assert update["speech"] == [f"The answer is: {QUESTION['expected_answer']}. {QUESTION['explanation']}"]
    assert update["mode"] is Mode.FEEDBACK
    assert "topics_to_improve" not in update  # not counted against them


def test_mark_to_improve_lists_each_topic_once():
    assert mark_to_improve([2], 0) == [0, 2]
    assert mark_to_improve([0, 2], 0) == [0, 2]


# --- moving on --------------------------------------------------------------


def test_topic_finished():
    assert not topic_finished(make_state(segment_index=1))
    assert topic_finished(make_state(segment_index=4))


def test_next_topic_moves_on_and_resets():
    update = next_topic(make_state(segment_index=4))
    assert update["current_topic"] == 1
    assert update["completed_topics"] == [0]
    assert update["segments"] == [] and update["question_points"] == []
    assert update["segment_index"] == 0


def test_next_topic_after_the_last_one_ends():
    update = next_topic(make_state(current_topic=1, completed_topics=[0], segment_index=4))
    assert update["current_topic"] is None
    assert update["completed_topics"] == [0, 1]
