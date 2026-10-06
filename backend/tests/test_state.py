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
        (True, 0, "praise"),  # right first time
        (False, 0, "hint"),  # first wrong answer -> hint and retry
        (True, 1, "praise"),  # right on the retry
        (False, 1, "reveal"),  # wrong again -> give the answer
    ],
)
def test_feedback_kind(correct, attempts, expected):
    assert feedback_kind(correct, attempts) == expected


@pytest.mark.parametrize(
    "mode, avatar, awaiting",
    [
        (Mode.EXPLAINING, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.FEEDBACK, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.ANSWERING_STUDENT, AvatarState.SPEAKING, Awaiting.CONTINUE),
        (Mode.AWAITING_ANSWER, AvatarState.ASKING_QUESTION, Awaiting.ANSWER),
        (Mode.AWAITING_STUDENT_QUESTION, AvatarState.LISTENING, Awaiting.QUESTION),
        (Mode.PAUSED, AvatarState.IDLE, Awaiting.OUTLINE),
        (Mode.ENDED, AvatarState.IDLE, Awaiting.NOTHING),
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
    assert "unregistered type" not in caplog.text  # our types are allowed
