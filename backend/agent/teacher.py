"""Step 11: all the nodes connected into one LangGraph graph, plus the two
calls the FastAPI routes use: start_session() and send_event().

The graph is always paused at the "wait" node. Each student event resumes it:
the event is routed to the right nodes, which update the state, and the graph
comes back to "wait" and pauses again.

    start:  plan -> explain -> wait

    wait --continue-->    continue -> ask_question | explain | next_topic -> (explain | closing)
    wait --answer-->      take_answer -> evaluate_answer
    wait --raise_hand-->  raise_hand
    wait --question-->    take_question -> answer_student_question
    wait --go_to_topic--> go_to_topic -> (explain if it's never been started)
    wait --repeat-->      choose_repeat -> repeat
    ... and every path ends back at wait. After the last topic: closing.

Usage (e.g. from FastAPI):
    teacher = Teacher()
    response = teacher.start_session(StartSessionRequest(...))
    response = teacher.send_event(response.session_id, ContinueEvent())
    teacher.end_session(response.session_id)   # "end session" button: deletes it
"""

import uuid

from langgraph.graph import START, StateGraph
from langgraph.types import Command, interrupt

from agent.contract import StartSessionRequest, StudentEvent, TeacherResponse
from agent.explaining import make_explain_node
from agent.hand_raise import make_answer_student_question_node, raise_hand
from agent.llm import LLM, get_llm
from agent.navigation import (
    after_continue,
    after_entering_topic,
    after_next_topic,
    can_continue,
    can_go_to_topic,
    can_repeat,
    choose_topic_to_repeat,
    continue_lecture,
    go_to_topic,
    make_closing_node,
    make_repeat_node,
)
from agent.planning import make_plan_node
from agent.questioning import make_ask_question_node, make_evaluate_answer_node, next_topic
from agent.state import Mode, TeacherState, initial_state, make_checkpointer, to_response


class SessionNotFound(Exception):
    """No lecture session with this id (wrong id, or the server restarted)."""


class EventNotAllowed(Exception):
    """The event doesn't make sense right now, e.g. an answer while Regina is explaining."""


# ---------------------------------------------------------------------------
# Is this event allowed right now?
# ---------------------------------------------------------------------------


def is_allowed(state: TeacherState, event: dict) -> bool:
    kind = event["type"]
    if kind == "continue":
        return can_continue(state)
    if kind == "answer":
        return state["mode"] == Mode.AWAITING_ANSWER
    if kind == "raise_hand":
        return state["mode"] == Mode.EXPLAINING
    if kind == "question":
        return state["mode"] == Mode.AWAITING_STUDENT_QUESTION
    if kind == "go_to_topic":
        return can_go_to_topic(state, event["topic_index"])
    if kind == "repeat":
        return can_repeat(state, event["topic_index"])
    return False


# ---------------------------------------------------------------------------
# The small nodes that turn an event into a state change
# ---------------------------------------------------------------------------


def wait(state: TeacherState) -> dict:
    """Pause until the next student event (Step 2's interrupt). Nothing goes before it."""
    event = interrupt("waiting for the student")
    return {"event": event}


def route_event(state: TeacherState) -> str:
    """After wait: which node handles the event."""
    return {
        "continue": "continue",
        "answer": "take_answer",
        "raise_hand": "raise_hand",
        "question": "take_question",
        "go_to_topic": "go_to_topic",
        "repeat": "choose_repeat",
    }[state["event"]["type"]]


def take_input(state: TeacherState) -> dict:
    return {"student_input": state["event"]["text"]}


def handle_raise_hand(state: TeacherState) -> dict:
    return raise_hand(state, state["event"]["segment_index"])


def handle_go_to_topic(state: TeacherState) -> dict:
    return go_to_topic(state, state["event"]["topic_index"])


def handle_choose_repeat(state: TeacherState) -> dict:
    return choose_topic_to_repeat(state, state["event"]["topic_index"])


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


def build_graph(llm: LLM, checkpointer=None):
    graph = StateGraph(TeacherState)

    # Nodes from steps 6-10
    graph.add_node("plan", make_plan_node(llm))
    graph.add_node("explain", make_explain_node(llm))
    graph.add_node("ask_question", make_ask_question_node(llm))
    graph.add_node("evaluate_answer", make_evaluate_answer_node(llm))
    graph.add_node("answer_student_question", make_answer_student_question_node(llm))
    graph.add_node("repeat", make_repeat_node(llm))
    graph.add_node("next_topic", next_topic)
    graph.add_node("closing", make_closing_node(llm))

    # Waiting, and handling events
    graph.add_node("wait", wait)
    graph.add_node("continue", continue_lecture)
    graph.add_node("take_answer", take_input)
    graph.add_node("take_question", take_input)
    graph.add_node("raise_hand", handle_raise_hand)
    graph.add_node("go_to_topic", handle_go_to_topic)
    graph.add_node("choose_repeat", handle_choose_repeat)

    # Start of a session
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "explain")

    # From wait, by event
    graph.add_conditional_edges(
        "wait",
        route_event,
        ["continue", "take_answer", "raise_hand", "take_question", "go_to_topic", "choose_repeat"],
    )
    graph.add_conditional_edges("continue", after_continue, ["ask_question", "explain", "next_topic"])
    graph.add_conditional_edges("next_topic", after_next_topic, ["explain", "wait", "closing"])
    graph.add_edge("take_answer", "evaluate_answer")
    graph.add_edge("take_question", "answer_student_question")
    graph.add_conditional_edges("go_to_topic", after_entering_topic, ["explain", "wait", "closing"])
    graph.add_edge("choose_repeat", "repeat")

    # Everything that speaks goes back to waiting
    for node in [
        "explain", "ask_question", "evaluate_answer", "answer_student_question",
        "raise_hand", "repeat", "closing",
    ]:
        graph.add_edge(node, "wait")

    return graph.compile(checkpointer=checkpointer or make_checkpointer())


# ---------------------------------------------------------------------------
# What the FastAPI routes call
# ---------------------------------------------------------------------------


class Teacher:
    """The teacher agent. Create one and share it across requests."""

    def __init__(self, llm: LLM | None = None, checkpointer=None):
        self.checkpointer = checkpointer or make_checkpointer()
        self.graph = build_graph(llm or get_llm(), self.checkpointer)

    def start_session(self, request: StartSessionRequest) -> TeacherResponse:
        """Plan the lecture and return Regina's first turn."""
        session_id = uuid.uuid4().hex
        self.graph.invoke(initial_state(session_id, request), _config(session_id))
        return self._response(session_id)

    def send_event(self, session_id: str, event: StudentEvent) -> TeacherResponse:
        """Handle one student event and return Regina's next turn.

        Raises SessionNotFound or EventNotAllowed (nothing changes then).
        """
        event_data = event.model_dump(mode="json")
        if not is_allowed(self._state(session_id), event_data):
            raise EventNotAllowed(f"'{event_data['type']}' isn't possible right now")
        self.graph.invoke(Command(resume=event_data), _config(session_id))
        return self._response(session_id)

    def end_session(self, session_id: str) -> None:
        """The "end session" button: delete the session completely. Nothing is kept."""
        self._state(session_id)  # raises SessionNotFound for an unknown id
        self.checkpointer.delete_thread(session_id)

    def get_session(self, session_id: str) -> TeacherResponse:
        """The current turn again, without changing anything (e.g. after a page reload)."""
        return self._response(session_id)

    def _state(self, session_id: str) -> TeacherState:
        values = self.graph.get_state(_config(session_id)).values
        if not values:
            raise SessionNotFound(session_id)
        return values

    def _response(self, session_id: str) -> TeacherResponse:
        return to_response(self._state(session_id))


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
