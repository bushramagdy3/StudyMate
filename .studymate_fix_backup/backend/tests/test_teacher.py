"""Whole lectures through the real graph, with a fake LLM that answers each
kind of prompt (plan, explain, question, grading, student question, goodbye)."""

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
    LectureChunk(slide=1, text="HTTP/1.1 pipelining sends requests without waiting."),
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


def start(teacher, environment=Environment.CAFE):  # café: 3 segments, 1 question per topic
    return teacher.start_session(StartSessionRequest(environment=environment, lecture=LECTURE))


def test_start_plans_and_starts_explaining(teacher):
    response = start(teacher)

    assert [t.title for t in response.outline] == ["Pipelining", "Head-of-Line Blocking"]
    assert response.current_topic == 0
    assert response.speech == ["e1-s0", "e1-s1", "e1-s2"]
    assert response.avatar_state is AvatarState.SPEAKING
    assert response.awaiting is Awaiting.CONTINUE
    assert response.can_raise_hand


def test_a_whole_lecture(teacher):
    session = start(teacher).session_id
    send = lambda event: teacher.send_event(session, event)

    question = send(ContinueEvent())  # explanation finished -> question
    assert question.speech == ["Why is it faster?"]
    assert question.awaiting is Awaiting.ANSWER

    hint = send(AnswerEvent(text="no idea"))  # wrong -> hint, same question
    assert hint.speech == ["Not quite, try again."]
    assert hint.awaiting is Awaiting.ANSWER

    praise = send(AnswerEvent(text="right, no waiting"))
    assert praise.speech == ["Correct!"]
    assert praise.awaiting is Awaiting.CONTINUE
    assert not praise.can_raise_hand  # feedback, not explaining

    topic2 = send(ContinueEvent())  # topic 1 done -> topic 2
    assert topic2.current_topic == 1
    assert topic2.completed_topics == [0]
    assert topic2.speech == ["e2-s0", "e2-s1", "e2-s2"]

    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    goodbye = send(ContinueEvent())  # last topic done -> goodbye
    assert goodbye.speech == ["Goodbye!"]
    assert goodbye.awaiting is Awaiting.NOTHING
    assert goodbye.completed_topics == [0, 1]

    with pytest.raises(EventNotAllowed):
        send(ContinueEvent())  # it's over


def test_two_wrong_answers_reveal_and_move_on(teacher):
    session = start(teacher).session_id
    teacher.send_event(session, ContinueEvent())
    teacher.send_event(session, AnswerEvent(text="no"))
    reveal = teacher.send_event(session, AnswerEvent(text="still no"))
    assert reveal.awaiting is Awaiting.CONTINUE  # feedback, then the lecture goes on
    assert teacher.send_event(session, ContinueEvent()).current_topic == 1


def test_raise_hand_and_resume_from_that_segment(teacher):
    session = start(teacher).session_id

    hand = teacher.send_event(session, RaiseHandEvent(segment_index=1))  # during e1-s1
    assert hand.awaiting is Awaiting.QUESTION
    assert hand.avatar_state is AvatarState.LISTENING

    answer = teacher.send_event(session, QuestionEvent(text="Is it used today?"))
    assert answer.speech == ["Good question. Okay, back to where we were."]
    assert not answer.can_raise_hand

    resumed = teacher.send_event(session, ContinueEvent())
    assert resumed.speech == ["e1-s1", "e1-s2"]  # replays from the interrupted segment


def test_click_another_topic_then_come_back_resumes(teacher):
    session = start(teacher).session_id
    teacher.send_event(session, RaiseHandEvent(segment_index=0))  # hand up, then changes mind

    topic2 = teacher.send_event(session, GoToTopicEvent(topic_index=1))
    assert topic2.current_topic == 1
    assert topic2.speech == ["e2-s0", "e2-s1", "e2-s2"]

    back = teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert back.current_topic == 0
    assert back.speech == ["e1-s0", "e1-s1", "e1-s2"]  # same explanation, no new LLM call


def test_clicking_a_topic_during_a_question_and_back_replays_that_part(teacher):
    session = start(teacher).session_id
    teacher.send_event(session, ContinueEvent())  # question waiting
    teacher.send_event(session, GoToTopicEvent(topic_index=1))
    back = teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert back.speech == ["e1-s0", "e1-s1", "e1-s2"]
    assert teacher.send_event(session, ContinueEvent()).speech == ["Why is it faster?"]


def test_replaying_a_finished_topic_returns_to_the_unfinished_one(teacher):
    session = start(teacher).session_id
    send = lambda event: teacher.send_event(session, event)
    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    send(ContinueEvent())  # topic 2 starts (e2)
    send(ContinueEvent())  # topic 2's question is waiting

    replay = send(GoToTopicEvent(topic_index=0))  # finished topic: same explanation
    assert replay.speech == ["e1-s0", "e1-s1", "e1-s2"]
    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    resumed = send(ContinueEvent())
    assert resumed.current_topic == 1  # back to the unfinished topic
    assert resumed.speech == ["e2-s0", "e2-s1", "e2-s2"]


def test_repeat_button_reprompts_for_a_new_explanation(teacher):
    session = start(teacher).session_id
    response = teacher.send_event(session, RepeatEvent(topic_index=0))
    assert response.speech == ["e2-s0", "e2-s1", "e2-s2"]  # a 2nd explanation was written
    assert response.awaiting is Awaiting.CONTINUE


def test_repeat_is_only_for_taught_topics(teacher):
    session = start(teacher).session_id
    with pytest.raises(EventNotAllowed):
        teacher.send_event(session, RepeatEvent(topic_index=1))


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
        AnswerEvent(text="hi"),  # no question was asked
        QuestionEvent(text="hi"),  # hand isn't raised
        GoToTopicEvent(topic_index=5),  # no such topic
        RepeatEvent(topic_index=1),  # not taught yet
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
    a = start(teacher).session_id
    b = start(teacher, Environment.LECTURE_HALL).session_id
    teacher.send_event(a, ContinueEvent())
    assert teacher.get_session(a).awaiting is Awaiting.ANSWER
    assert teacher.get_session(b).awaiting is Awaiting.CONTINUE


def test_a_long_lecture_does_not_hit_langgraph_limits():
    transport, _ = fake_featherless()
    teacher = Teacher(llm=LLM("key", "model", transport=transport))
    session = start(teacher).session_id
    for _ in range(30):  # many turns in one session
        teacher.send_event(session, GoToTopicEvent(topic_index=1))
        teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert teacher.get_session(session).awaiting is Awaiting.CONTINUE


def test_two_question_topic_continues_with_the_next_part_after_feedback(teacher):
    # Professor: 2 questions per topic. The fake's [3] is invalid for 2 questions,
    # so the default points [2, 3] are used: parts [s0, s1] and [s2].
    session = start(teacher, Environment.LECTURE_HALL)
    assert session.speech == ["e1-s0", "e1-s1"]

    send = lambda event: teacher.send_event(session.session_id, event)
    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    part2 = send(ContinueEvent())
    assert part2.speech == ["e1-s2"]  # same topic, next part
    assert part2.current_topic == 0

    send(ContinueEvent())
    send(AnswerEvent(text="right"))
    assert send(ContinueEvent()).current_topic == 1  # now the next topic


def test_no_langgraph_warnings_about_saved_types(teacher, caplog):
    session = start(teacher).session_id
    teacher.send_event(session, ContinueEvent())
    teacher.send_event(session, GoToTopicEvent(topic_index=1))
    assert "unregistered type" not in caplog.text


def test_tutor_summary_then_back_to_the_lecture(teacher):
    first = start(teacher, Environment.STUDY_ROOM)
    assert first.summary_available
    session = first.session_id
    teacher.send_event(session, ContinueEvent())  # a question is waiting

    summary = teacher.send_event(session, SummaryEvent())
    assert summary.speech == ["Summary part 1.", "Summary part 2."]
    assert summary.awaiting is Awaiting.CONTINUE
    assert not summary.can_raise_hand

    back = teacher.send_event(session, ContinueEvent())
    assert back.speech == ["e1-s0", "e1-s1"]  # the part the question was about
    assert teacher.send_event(session, ContinueEvent()).speech == ["Why is it faster?"]


def test_summary_is_not_available_for_other_personalities(teacher):
    response = start(teacher)  # café
    assert not response.summary_available
    with pytest.raises(EventNotAllowed):
        teacher.send_event(response.session_id, SummaryEvent())
