import pytest
from langgraph.graph import END, START, StateGraph

from agent.contract import Awaiting, AvatarState, Environment, LectureChunk, StartSessionRequest
from agent.state import Mode, TeacherState, feedback_kind, initial_state, make_checkpointer, to_response

REQUEST = StartSessionRequest(
    environment=Environment.STUDY_ROOM,
    lecture=[LectureChunk(slide=1, text="HTTP/1.1 pipelining")],
)

TOPIC = {
    "title": "Pipelining",
    "summary": "Sending requests without waiting",
    "key_points": ["no waiting"],
    "source_slides": [1],
}


def test_initial_state():
    state = initial_state("abc", REQUEST)
    assert state["environment"] is Environment.STUDY_ROOM
    assert state["current_topic"] is None
    assert state["outline"] == [] and state["history"] == []


@pytest.mark.parametrize(
    "correct, attempts, expected",
    [
        (True, 0, "praise"),
        (False, 0, "hint"),
        (True, 1, "praise"),
        (False, 1, "reveal"),
    ],
)
def test_feedback_kind(correct, attempts, expected):
    assert feedback_kind(correct, attempts) == expected


@pytest.mark.parametrize(
    "mode, avatar, awaiting",
    [
        (Mode.INTRO, AvatarState.SPEAKING, Awaiting.CONTINUE),
        # Waiting / ended still speak the "next topic" or "quiz is next" line.
        (Mode.WAITING_TOPIC, AvatarState.SPEAKING, Awaiting.NOTHING),
        (Mode.EXPLAINING, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.FEEDBACK, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.ANSWERING_STUDENT, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.SUMMARIZING, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.AWAITING_ANSWER, AvatarState.ASKING_QUESTION, Awaiting.ANSWER),
        (Mode.AWAITING_STUDENT_QUESTION, AvatarState.LISTENING, Awaiting.QUESTION),
        (Mode.ENDED, AvatarState.SPEAKING, Awaiting.NOTHING),
    ],
)
def test_to_response_maps_mode(mode, avatar, awaiting):
    state = initial_state("abc", REQUEST) | {
        "mode": mode,
        "outline": [TOPIC],
        "current_topic": 0,
        "speech": ["Hi!"],
    }
    response = to_response(state)
    assert (response.avatar_state, response.awaiting) == (avatar, awaiting)
    assert response.outline[0].title == "Pipelining"
    assert response.speech == ["Hi!"]


def test_state_survives_the_checkpointer(caplog):
    """The state (including pydantic objects and the history reducer) is saved and reloaded."""

    def plan(state: TeacherState) -> dict:
        return {
            "outline": [TOPIC],
            "current_topic": 0,
            "history": [{"role": "teacher", "text": "Welcome!"}],
        }

    graph = StateGraph(TeacherState)
    graph.add_node("plan", plan)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", END)
    app = graph.compile(checkpointer=make_checkpointer())

    config = {"configurable": {"thread_id": "abc"}}
    app.invoke(initial_state("abc", REQUEST), config)
    saved = app.get_state(config).values

    assert saved["lecture"][0] == LectureChunk(slide=1, text="HTTP/1.1 pipelining")
    assert saved["environment"] is Environment.STUDY_ROOM
    assert saved["history"] == [{"role": "teacher", "text": "Welcome!"}]
    assert to_response(saved).current_topic == 0
    assert "unregistered type" not in caplog.text


def test_summary_is_available_only_for_the_tutor():
    tutor = initial_state("abc", REQUEST) | {"outline": [TOPIC], "current_topic": 0}
    assert to_response(tutor).summary_available
    assert not to_response(tutor | {"mode": Mode.ENDED}).summary_available
    cafe = initial_state("abc", StartSessionRequest(environment=Environment.CAFE, lecture=REQUEST.lecture))
    assert not to_response(cafe | {"outline": [TOPIC], "current_topic": 0}).summary_available


# --- lecture progress and speech rate -------------------------------------------

FOUR_TOPICS = [TOPIC | {"title": f"Topic {n}"} for n in range(4)]


def progress_state(**fields):
    return initial_state("abc", REQUEST) | {"outline": FOUR_TOPICS, "mode": Mode.WAITING_TOPIC} | fields


def test_progress_counts_finished_topics():
    assert to_response(progress_state()).lecture_progress == 0
    assert to_response(progress_state(completed_topics=[0, 2])).lecture_progress == 0.5
    assert to_response(progress_state(completed_topics=[0, 1, 2, 3])).lecture_progress == 1


def test_progress_counts_how_much_of_the_current_topic_was_said():
    state = progress_state(
        completed_topics=[0, 1, 2],
        current_topic=3,
        segments=["a", "b", "c", "d"],
        segment_index=2,  # half of topic 3 said
        mode=Mode.EXPLAINING,
    )
    assert to_response(state).lecture_progress == 0.875  # (3 + 0.5) / 4


def test_progress_counts_topics_left_halfway():
    saved = {"segments": ["a", "b"], "question_points": [2], "segment_index": 1}
    assert to_response(progress_state(topic_progress={1: saved})).lecture_progress == 0.125


def test_an_unfinished_topic_never_shows_as_complete():
    state = progress_state(current_topic=0, segments=["a", "b"], segment_index=2, mode=Mode.FEEDBACK)
    assert to_response(state).lecture_progress < 0.25


@pytest.mark.parametrize("pace, rate", [("slow", 0.9), ("normal", 1.0), ("quick", 1.1)])
def test_speech_rate_follows_the_pace_while_explaining(pace, rate):
    state = progress_state(current_topic=0, segments=["a"], mode=Mode.EXPLAINING, pace=pace, speech=["a"])
    assert to_response(state).speech_rate == rate
    # Questions, feedback and other talk are always at normal speed.
    assert to_response(state | {"mode": Mode.FEEDBACK}).speech_rate == 1.0
