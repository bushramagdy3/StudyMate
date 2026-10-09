import json

import httpx
import pytest

from agent import llm as llm_module
from agent import planning
from agent.contract import Environment, LectureChunk, StartSessionRequest
from agent.llm import LLM
from agent.planning import (
    fallback_outline,
    intro_speech,
    make_plan_node,
    plan_lecture,
    slides_text,
    topic_range,
)
from agent.state import Mode, initial_state

LECTURE = [
    LectureChunk(slide=1, text="Web Protocols\nLecture 4"),
    LectureChunk(slide=2, text="HTTP/1.1 pipelining sends requests without waiting."),
    LectureChunk(slide=3, text="Head-of-line blocking: one slow response blocks the rest."),
    LectureChunk(slide=4, text="HTTP/2 multiplexing sends many streams over one connection."),
]

PLAN = {
    "topics": [
        {
            "title": "HTTP/1.1 Pipelining",
            "summary": "How pipelining sends requests without waiting.",
            "key_points": ["several requests at once", " "],
            "source_slides": [2, 2, 99],
        },
        {
            "title": "Head-of-Line Blocking",
            "summary": "Why one slow response delays the others.",
            "key_points": ["responses come back in order"],
            "source_slides": [3],
        },
    ]
}


def json_reply(data) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(data)}}]})


def fake_llm(handler) -> tuple[LLM, list[dict]]:
    sent = []

    def record(request):
        body = json.loads(request.content)
        sent.append(body)
        return handler(body)

    return LLM("key", "model", transport=httpx.MockTransport(record)), sent


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


def test_plan_lecture_returns_clean_outline():
    llm, sent = fake_llm(lambda body: json_reply(PLAN))
    outline = plan_lecture(llm, LECTURE)

    assert [topic["title"] for topic in outline] == ["HTTP/1.1 Pipelining", "Head-of-Line Blocking"]
    assert outline[0]["source_slides"] == [2]
    assert outline[0]["key_points"] == ["several requests at once"]

    prompt = sent[0]["messages"][1]["content"]
    assert "Slide 3:\nHead-of-line blocking" in prompt
    assert "between 1 and 4 small topics" in prompt


def test_topic_range_scales_with_slides():
    assert topic_range(1) == (1, 3)
    assert topic_range(10) == (4, 7)
    assert topic_range(60) == (12, 12)


def test_too_many_topics_are_cut():
    many = {"topics": [{**PLAN["topics"][0], "title": f"Topic {i}"} for i in range(20)]}
    llm, _ = fake_llm(lambda body: json_reply(many))
    assert len(plan_lecture(llm, LECTURE)) == planning.MAX_TOPICS


def test_llm_failure_falls_back_to_slide_groups():
    llm, _ = fake_llm(lambda body: httpx.Response(503))
    outline = plan_lecture(llm, LECTURE)
    assert outline == fallback_outline(LECTURE)
    assert [topic["source_slides"] for topic in outline] == [[1, 2, 3], [4]]
    assert outline[0]["title"] == "Web Protocols"


def test_long_lectures_are_condensed_before_planning(monkeypatch):
    monkeypatch.setattr(planning, "MAX_PLANNING_CHARS", 100)
    monkeypatch.setattr(planning, "CONDENSE_BATCH_CHARS", 120)

    def handler(body):
        prompt = body["messages"][1]["content"]
        if "short notes" in prompt:
            slides = [int(line.split()[1][:-1]) for line in prompt.splitlines() if line.startswith("Slide ")]
            return json_reply({"slides": [{"slide": s, "notes": f"notes {s}"} for s in slides]})
        return json_reply(PLAN)

    llm, sent = fake_llm(handler)
    outline = plan_lecture(llm, LECTURE)

    condense_calls = [b for b in sent if "short notes" in b["messages"][1]["content"]]
    assert len(condense_calls) == 2
    planning_prompt = sent[-1]["messages"][1]["content"]
    assert "Slide 4:\nnotes 4" in planning_prompt
    assert outline[1]["title"] == "Head-of-Line Blocking"


def test_slides_text_returns_full_slide_content():
    text = slides_text(LECTURE, [2, 3])
    assert text == (
        "Slide 2:\nHTTP/1.1 pipelining sends requests without waiting.\n\n"
        "Slide 3:\nHead-of-line blocking: one slow response blocks the rest."
    )


def test_plan_node_sets_up_intro_and_waits_for_topic_choice():
    llm, _ = fake_llm(lambda body: json_reply(PLAN))
    state = initial_state("abc", StartSessionRequest(environment=Environment.CAFE, lecture=LECTURE))

    update = make_plan_node(llm)(state)

    assert len(update["outline"]) == 2
    assert update["current_topic"] is None
    assert update["current_slide"] == 1
    assert update["segment_index"] == 0
    assert update["mode"] is Mode.INTRO
    assert update["speech"]
    assert "HTTP/1.1 Pipelining" in update["speech"][0]
    assert "Choose a topic" in update["speech"][0]


def test_intro_uses_the_planned_content_when_there_is_no_title_slide():
    titleless_lecture = [
        LectureChunk(slide=1, text="A 2-inch image on a 200 DPI screen uses 400 pixels."),
    ]
    outline = [
        {
            "title": "Pixels and DPI",
            "summary": "How physical image size and display density determine pixel dimensions.",
            "key_points": ["pixels per inch"],
            "source_slides": [1],
        }
    ]

    intro = intro_speech(titleless_lecture, outline, Environment.STUDY_ROOM)

    assert "today's lecture" not in intro.lower()
    assert "Pixels and DPI" in intro
    assert "display density" in intro
