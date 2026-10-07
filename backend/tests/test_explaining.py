import json

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import Environment, LectureChunk, StartSessionRequest
from agent.explaining import (
    add_slide_transitions,
    choose_question_points,
    default_question_points,
    explain_prompt,
    fallback_segments,
    fit_segments,
    generate_segments,
    make_explain_node,
    next_stop,
)
from agent.llm import LLM
from agent.state import Mode, initial_state

LECTURE = [
    LectureChunk(slide=1, text="Web Protocols"),
    LectureChunk(slide=2, text="HTTP/1.1 pipelining sends requests without waiting."),
    LectureChunk(slide=3, text="Head-of-line blocking: one slow response blocks the rest."),
]

OUTLINE = [
    {
        "title": "Pipelining",
        "summary": "Sending requests without waiting.",
        "key_points": ["several requests at once"],
        "source_slides": [2],
    },
    {
        "title": "Head-of-Line Blocking",
        "summary": "Why one slow response delays the others.",
        "key_points": ["responses come back in order"],
        "source_slides": [3],
    },
]


def make_state(environment=Environment.LECTURE_HALL, topic=0, **fields):
    state = initial_state("abc", StartSessionRequest(environment=environment, lecture=LECTURE))
    return state | {"outline": OUTLINE, "current_topic": topic} | fields


def fake_llm(segments=None, question_after=None, status=200):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status)
        content = json.dumps({"segments": segments, "question_after": question_after or []})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return LLM("key", "model", transport=httpx.MockTransport(handler)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


@pytest.mark.parametrize(
    "segments, questions, expected",
    [(4, 2, [2, 4]), (3, 1, [3]), (3, 2, [2, 3]), (1, 2, [1]), (5, 3, [2, 3, 5])],
)
def test_default_question_points(segments, questions, expected):
    assert default_question_points(segments, questions) == expected


def test_llm_question_points_are_used_when_valid():
    assert choose_question_points([1, 4], 4, 2) == [1, 4]
    assert choose_question_points([3, 4], 4, 2) == [3, 4]
    assert choose_question_points([3], 3, 1) == [3]


@pytest.mark.parametrize(
    "proposed",
    [
        [2],  # too few questions
        [1, 2, 4],  # too many
        [1, 3],  # last question not at the end
        [0, 4],  # not a real segment number
        [4, 4],  # duplicate
        [],
    ],
)
def test_invalid_llm_question_points_use_the_default(proposed):
    assert choose_question_points(proposed, 4, 2) == [2, 4]


def test_next_stop():
    assert next_stop(0, [1, 4], 4) == 1
    assert next_stop(1, [1, 4], 4) == 4
    assert next_stop(2, [1, 4], 4) == 4  # resuming mid-part ends at the same question


def test_fit_segments_merges_extras_and_drops_blanks():
    assert fit_segments(["a", " ", "b", "c", "d"], 3) == ["a", "b", "c d"]
    assert fit_segments(["a", "b"], 3) == ["a", "b"]


def test_prompt_uses_personality_and_slides_without_a_second_introduction():
    llm, sent = fake_llm(["one", "two", "three", "four"])
    generate_segments(llm, make_state())

    system, user = sent[0]["messages"][0]["content"], sent[0]["messages"][1]["content"]
    assert "Professor Regina" in system
    assert "Slide 2:\nHTTP/1.1 pipelining" in user
    assert "Head-of-line" not in user
    assert "Do not greet the student or introduce yourself again" in user
    assert "This is the very start of the lecture" not in user
    assert "exactly 4 segments" in user
    assert "exactly 2 segment number(s) between 1 and 4" in user


def test_later_topics_connect_to_covered_ones_without_greeting():
    state = make_state(topic=1, completed_topics=[0], history=[{"role": "teacher", "text": "Hi"}])
    prompt = explain_prompt(state)
    assert "Already covered: Pipelining" in prompt
    assert "greeting" not in prompt


def test_jumping_ahead_doesnt_count_skipped_topics_as_covered():
    prompt = explain_prompt(make_state(topic=1, history=[{"role": "teacher", "text": "Hi"}]))
    assert "Already covered" not in prompt


def test_going_back_to_the_first_topic_doesnt_greet_again():
    state = make_state(topic=0, completed_topics=[0, 1], history=[{"role": "teacher", "text": "Hi"}])
    prompt = explain_prompt(state)
    assert "greeting" not in prompt
    assert "Already covered: Head-of-Line Blocking" in prompt


def test_repeat_asks_for_a_different_explanation():
    prompt = explain_prompt(make_state(), previous=["Pipelining is when..."])
    assert '"Pipelining is when..."' in prompt
    assert "differently" in prompt
    assert "greeting" not in prompt


def test_llm_failure_uses_fallback_segments():
    llm, _ = fake_llm(status=503)
    segments, points = generate_segments(llm, make_state())
    assert segments == [
        "Let's look at Pipelining.",
        "Sending requests without waiting.",
        "several requests at once.",
    ]
    assert points == [2, 3]  # questions stay at the ends of the original idea groups
    assert fallback_segments(OUTLINE[0]) == [
        "Let's look at Pipelining. Sending requests without waiting.",
        "several requests at once.",
    ]


def test_new_topic_says_the_first_part_only():
    llm, _ = fake_llm(["s0", "s1", "s2", "s3"], question_after=[1, 4])
    update = make_explain_node(llm)(make_state())  # professor: 2 questions

    assert update["segments"] == ["s0", "s1", "s2", "s3"]
    assert update["question_points"] == [1, 4]  # the LLM's choice
    assert update["speech"] == ["s0"]
    assert update["segment_index"] == 0
    assert update["mode"] is Mode.EXPLAINING
    assert update["history"] == [{"role": "teacher", "text": "s0"}]


def test_continues_from_segment_index_without_rewriting():
    llm, sent = fake_llm(["should not be used"])
    state = make_state(segments=["s0", "s1", "s2", "s3"], segment_index=2)
    update = make_explain_node(llm)(state | {"question_points": [2, 4]})

    assert update["speech"] == ["s2", "s3"]
    assert sent == []  # no LLM call


def test_resume_after_raised_hand_replays_from_that_segment():
    llm, _ = fake_llm()
    state = make_state(segments=["s0", "s1", "s2", "s3"], segment_index=1, question_points=[2, 4])
    assert make_explain_node(llm)(state)["speech"] == ["s1"]


def test_one_question_personality_says_the_whole_topic():
    llm, _ = fake_llm(["s0", "s1", "s2"], question_after=[3])
    update = make_explain_node(llm)(make_state(environment=Environment.CAFE))
    assert update["speech"] == ["s0", "s1", "s2"]


def test_bad_llm_question_points_fall_back_to_default():
    llm, _ = fake_llm(["s0", "s1", "s2", "s3"], question_after=[1, 2])  # last not at the end
    update = make_explain_node(llm)(make_state())
    assert update["question_points"] == [2, 4]
    assert update["speech"] == ["s0", "s1"]


def test_slide_transitions_are_spoken_and_keep_question_boundaries():
    segments, points, slides = add_slide_transitions(
        ["first", "second", "third", "fourth"],
        [2, 4],
        [2, 3],
    )

    assert segments == [
        "first",
        "second",
        "[thoughtful] Let me show you the next slide.",
        "third",
        "fourth",
    ]
    assert slides == [2, 2, 3, 3, 3]
    assert points == [2, 5]


def test_explanation_response_pairs_each_played_segment_with_a_slide():
    multi_slide_outline = OUTLINE[:1]
    multi_slide_outline[0] = multi_slide_outline[0] | {"source_slides": [2, 3]}
    llm, _ = fake_llm(["first", "second", "third", "fourth"], question_after=[2, 4])
    update = make_explain_node(llm)(
        make_state(outline=multi_slide_outline)
    )

    assert update["speech"] == ["first", "second"]
    assert update["speech_slides"] == [2, 2]
    assert update["segment_slides"] == [2, 2, 3, 3, 3]
