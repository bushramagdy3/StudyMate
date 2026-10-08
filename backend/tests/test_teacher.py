"""Whole lectures through the real graph, with a fake LLM that answers each
kind of prompt (plan, explain, question, grading, student question, summary)."""

import json

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import (
    AnswerEvent,
    Awaiting,
    AvatarState,
    ContinueEvent,
    Environment,
    GoToTopicEvent,
    LectureChunk,
    QuestionEvent,
    RaiseHandEvent,
    RepeatEvent,
    StartSessionRequest,
    SummaryEvent,
)
from agent.llm import LLM
from agent.teacher import EventNotAllowed, SessionNotFound, Teacher

LECTURE = [
    LectureChunk(slide=1, text="HTTP Performance\nHTTP/1.1 pipelining sends requests without waiting."),
    LectureChunk(slide=2, text="Head-of-line blocking: one slow response blocks the rest."),
]

PLAN = {
    "topics": [
        {"title": "Pipelining", "summary": "No waiting.", "key_points": ["overlap"], "source_slides": [1]},
        {"title": "Head-of-Line Blocking", "summary": "Slow blocks fast.", "key_points": ["order"], "source_slides": [2]},
    ]
}


def fake_featherless():
    """Replies like Kimi would, depending on which prompt it receives."""
    calls = {"explain": 0}

    def handler(request):
        prompt = json.loads(request.content)["messages"][-1]["content"]
        full = json.loads(request.content)["messages"][1]["content"]

        if "lecture is finished" in full:
            return text_reply("Goodbye!")
        if "summary of the entire lecture" in full:
            return text_reply(json.dumps({"segments": ["Summary part 1.", "Summary part 2."]}))
        if "Split this lecture" in full:
            reply = PLAN
        elif "Write the explanation" in full:
            calls["explain"] += 1
            n = calls["explain"]
            reply = {"segments": [f"e{n}-s0", f"e{n}-s1", f"e{n}-s2"], "question_after": [3]}
        elif "Ask the student ONE question" in full:
            reply = {"question": "Why is it faster?", "expected_answer": "no waiting", "explanation": "Overlap."}
        elif "The student answered" in full:
            correct = '"right' in full.split("The student answered:")[1]
            reply = {"correct": correct, "response": "Correct!" if correct else "Not quite, try again."}
        elif "raised their hand and asked" in full:
            return text_reply("Good question. Okay, back to where we were.")
        else:
            raise AssertionError(f"unexpected prompt: {prompt[:80]}")
        return text_reply(json.dumps(reply))

    return httpx.MockTransport(handler), calls


def text_reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


@pytest.fixture
def teacher():
    transport, _ = fake_featherless()
    return Teacher(llm=LLM("key", "model", transport=transport))


def start(teacher, environment=Environment.CAFE):
    return teacher.start_session(StartSessionRequest(environment=environment, lecture=LECTURE))


def finish_intro(teacher, session_id):
    return teacher.send_event(session_id, ContinueEvent())


def start_topic(teacher, session_id, topic=0):
    return teacher.send_event(session_id, GoToTopicEvent(topic_index=topic))


def ready_topic(teacher, environment=Environment.CAFE, topic=0):
    first = start(teacher, environment)
    finish_intro(teacher, first.session_id)
    return start_topic(teacher, first.session_id, topic)


def test_start_returns_intro_before_any_topic(teacher):
    response = start(teacher)

    assert [t.title for t in response.outline] == ["Pipelining", "Head-of-Line Blocking"]
    assert response.current_topic is None
    assert response.current_slide == 1
    assert len(response.speech) == 1
    assert "HTTP Performance" in response.speech[0]
    assert "Choose a topic" in response.speech[0]
    assert response.avatar_state is AvatarState.SPEAKING
    assert response.awaiting is Awaiting.CONTINUE
    assert not response.can_raise_hand


def test_intro_finishes_then_waits_for_student_topic_choice(teacher):
    first = start(teacher)
    waiting = finish_intro(teacher, first.session_id)

    assert waiting.current_topic is None
    assert waiting.speech == []
    assert waiting.awaiting is Awaiting.NOTHING
    assert waiting.avatar_state is AvatarState.IDLE

    topic = start_topic(teacher, first.session_id, 0)
    assert topic.current_topic == 0
    assert topic.speech == ["e1-s0", "e1-s1", "e1-s2"]
    assert topic.awaiting is Awaiting.CONTINUE


def test_a_whole_lecture_uses_manual_topic_selection(teacher):
    first = start(teacher)
    session = first.session_id
    send = lambda event: teacher.send_event(session, event)

    send(ContinueEvent())
    topic1 = send(GoToTopicEvent(topic_index=0))
    assert topic1.speech == ["e1-s0", "e1-s1", "e1-s2"]

    question = send(ContinueEvent())
    assert question.speech == ["Why is it faster?"]
    assert question.awaiting is Awaiting.ANSWER

    hint = send(AnswerEvent(text="no idea"))
    assert hint.speech == ["Not quite, try again."]
    assert hint.awaiting is Awaiting.ANSWER

    praise = send(AnswerEvent(text="right, no waiting"))
    assert praise.speech == ["Correct!"]
    assert praise.awaiting is Awaiting.CONTINUE

    waiting = send(ContinueEvent())
    assert waiting.current_topic is None
    assert waiting.completed_topics == [0]
    assert "Next, we will explore Head-of-Line Blocking" in waiting.speech[0]
    assert not waiting.quiz_available  # a topic is still left

    topic2 = send(GoToTopicEvent(topic_index=1))
    assert topic2.current_topic == 1
    assert topic2.speech == ["e2-s0", "e2-s1", "e2-s2"]

    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    done = send(ContinueEvent())
    assert done.current_topic is None
    assert done.completed_topics == [0, 1]
    assert done.awaiting is Awaiting.NOTHING
    assert done.quiz_available


def test_two_wrong_answers_reveal_then_wait_for_outline(teacher):
    topic = ready_topic(teacher)
    session = topic.session_id
    teacher.send_event(session, ContinueEvent())
    teacher.send_event(session, AnswerEvent(text="no"))
    reveal = teacher.send_event(session, AnswerEvent(text="still no"))
    assert reveal.awaiting is Awaiting.CONTINUE
    waiting = teacher.send_event(session, ContinueEvent())
    assert waiting.current_topic is None
    assert waiting.completed_topics == [0]


def test_raise_hand_and_resume_from_that_segment(teacher):
    topic = ready_topic(teacher)
    session = topic.session_id

    hand = teacher.send_event(session, RaiseHandEvent(segment_index=1))
    assert hand.awaiting is Awaiting.QUESTION
    assert hand.avatar_state is AvatarState.LISTENING

    answer = teacher.send_event(session, QuestionEvent(text="Is it used today?"))
    assert answer.speech == ["Good question. Okay, back to where we were."]
    assert not answer.can_raise_hand

    resumed = teacher.send_event(session, ContinueEvent())
    assert resumed.speech == ["e1-s1", "e1-s2"]


def test_click_another_topic_then_come_back_resumes(teacher):
    topic1 = ready_topic(teacher)
    session = topic1.session_id
    teacher.send_event(session, RaiseHandEvent(segment_index=0))

    topic2 = teacher.send_event(session, GoToTopicEvent(topic_index=1))
    assert topic2.current_topic == 1
    assert topic2.speech == ["e2-s0", "e2-s1", "e2-s2"]

    back = teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert back.current_topic == 0
    assert back.speech == ["e1-s0", "e1-s1", "e1-s2"]


def test_clicking_a_topic_during_a_question_and_back_replays_that_part(teacher):
    topic1 = ready_topic(teacher)
    session = topic1.session_id
    teacher.send_event(session, ContinueEvent())
    teacher.send_event(session, GoToTopicEvent(topic_index=1))
    back = teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert back.speech == ["e1-s0", "e1-s1", "e1-s2"]
    assert teacher.send_event(session, ContinueEvent()).speech == ["Why is it faster?"]


def test_replay_finished_topic_does_not_auto_start_another_topic(teacher):
    topic1 = ready_topic(teacher)
    session = topic1.session_id
    send = lambda event: teacher.send_event(session, event)

    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    send(ContinueEvent())

    replay = send(RepeatEvent(topic_index=0))
    assert replay.speech == ["e2-s0", "e2-s1", "e2-s2"]
    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    waiting = send(ContinueEvent())
    assert waiting.current_topic is None
    assert waiting.completed_topics == [0]


def test_repeat_button_reprompts_for_a_new_explanation(teacher):
    topic = ready_topic(teacher)
    response = teacher.send_event(topic.session_id, RepeatEvent(topic_index=0))
    assert response.speech == ["e2-s0", "e2-s1", "e2-s2"]
    assert response.awaiting is Awaiting.CONTINUE


def test_repeat_is_only_for_taught_topics(teacher):
    first = start(teacher)
    finish_intro(teacher, first.session_id)
    with pytest.raises(EventNotAllowed):
        teacher.send_event(first.session_id, RepeatEvent(topic_index=1))


def test_end_session_deletes_everything(teacher):
    session = start(teacher).session_id
    teacher.end_session(session)
    with pytest.raises(SessionNotFound):
        teacher.get_session(session)
    with pytest.raises(SessionNotFound):
        teacher.send_event(session, ContinueEvent())


@pytest.mark.parametrize(
    "event",
    [
        AnswerEvent(text="hi"),
        QuestionEvent(text="hi"),
        GoToTopicEvent(topic_index=5),
        RepeatEvent(topic_index=1),
    ],
)
def test_events_at_the_wrong_time_are_rejected_and_change_nothing(teacher, event):
    first = start(teacher)
    with pytest.raises(EventNotAllowed):
        teacher.send_event(first.session_id, event)
    assert teacher.get_session(first.session_id) == first


def test_unknown_session(teacher):
    with pytest.raises(SessionNotFound):
        teacher.send_event("nope", ContinueEvent())


def test_sessions_are_independent(teacher):
    a = start(teacher)
    b = start(teacher, Environment.LECTURE_HALL)
    finish_intro(teacher, a.session_id)
    start_topic(teacher, a.session_id, 0)
    teacher.send_event(a.session_id, ContinueEvent())
    assert teacher.get_session(a.session_id).awaiting is Awaiting.ANSWER
    assert teacher.get_session(b.session_id).awaiting is Awaiting.CONTINUE
    assert teacher.get_session(b.session_id).current_topic is None


def test_a_long_lecture_does_not_hit_langgraph_limits(teacher):
    first = start(teacher)
    session = first.session_id
    finish_intro(teacher, session)
    start_topic(teacher, session, 0)
    for _ in range(30):
        teacher.send_event(session, GoToTopicEvent(topic_index=1))
        teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert teacher.get_session(session).awaiting is Awaiting.CONTINUE


def test_two_question_topic_continues_with_the_next_part_after_feedback(teacher):
    topic = ready_topic(teacher, Environment.LECTURE_HALL)
    assert topic.speech == ["e1-s0", "e1-s1"]

    send = lambda event: teacher.send_event(topic.session_id, event)
    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    part2 = send(ContinueEvent())
    assert part2.speech == ["e1-s2"]
    assert part2.current_topic == 0

    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    waiting = send(ContinueEvent())
    assert waiting.current_topic is None
    assert waiting.completed_topics == [0]


def test_no_langgraph_warnings_about_saved_types(teacher, caplog):
    topic = ready_topic(teacher)
    session = topic.session_id
    teacher.send_event(session, ContinueEvent())
    teacher.send_event(session, GoToTopicEvent(topic_index=1))
    assert "unregistered type" not in caplog.text


def test_tutor_summary_before_any_topic_returns_to_outline(teacher):
    first = start(teacher, Environment.STUDY_ROOM)
    assert first.summary_available
    session = first.session_id
    waiting = teacher.send_event(session, ContinueEvent())
    assert waiting.current_topic is None

    summary = teacher.send_event(session, SummaryEvent())
    assert summary.speech == ["Summary part 1.", "Summary part 2."]
    assert summary.awaiting is Awaiting.CONTINUE

    back = teacher.send_event(session, ContinueEvent())
    assert back.current_topic is None
    assert back.speech == []
    assert back.awaiting is Awaiting.NOTHING


def test_tutor_summary_during_topic_returns_to_the_lecture(teacher):
    topic = ready_topic(teacher, Environment.STUDY_ROOM)
    session = topic.session_id
    teacher.send_event(session, ContinueEvent())

    summary = teacher.send_event(session, SummaryEvent())
    assert summary.speech == ["Summary part 1.", "Summary part 2."]
    assert summary.awaiting is Awaiting.CONTINUE

    back = teacher.send_event(session, ContinueEvent())
    assert back.speech == ["e1-s0", "e1-s1"]
    assert teacher.send_event(session, ContinueEvent()).speech == ["Why is it faster?"]


def test_summary_is_not_available_for_other_personalities(teacher):
    response = start(teacher)
    assert not response.summary_available
    with pytest.raises(EventNotAllowed):
        teacher.send_event(response.session_id, SummaryEvent())
