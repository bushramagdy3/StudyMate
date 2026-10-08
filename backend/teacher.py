"""Step 11: all the nodes connected into one LangGraph graph, plus the two
calls the FastAPI routes use: start_session() and send_event().

The graph is always paused at the "wait" node. Each student event resumes it:
the event is routed to the right nodes, which update the state, and the graph
comes back to "wait" and pauses again.

    start:  plan -> wait                       (intro is returned first)

    wait --continue-->    continue -> finish_intro | ask_question | explain | next_topic
    wait --answer-->      take_answer -> evaluate_answer
    wait --raise_hand-->  raise_hand
    wait --question-->    take_question -> answer_student_question
    wait --go_to_topic--> go_to_topic -> (explain if it's never been started)
    wait --repeat-->      choose_repeat -> repeat
    wait --summary-->     summary   (then continue -> back_to_lecture -> where they were)

Usage (e.g. from FastAPI):
    teacher = Teacher()
    response = teacher.start_session(StartSessionRequest(...))
    response = teacher.send_event(response.session_id, ContinueEvent())
    teacher.end_session(response.session_id)   # "end session" button: deletes it

The quiz (after every topic is completed) isn't part of the graph: it doesn't
change the lecture, so start_quiz() and submit_quiz() keep it next to it.
"""

import random
import threading
import uuid

from langgraph.graph import START, StateGraph
from langgraph.types import Command, interrupt

from agent.contract import Quiz, QuizResult, StartSessionRequest, StudentEvent, TeacherResponse
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
    finish_intro,
    go_to_topic,
    make_closing_node,
    make_repeat_node,
)
from agent.planning import make_plan_node
from agent.quiz import QuizRecord, answers_problem, mark_quiz, new_quiz, restart_quiz, to_quiz
from agent.questioning import make_ask_question_node, make_evaluate_answer_node, next_topic
from agent.state import (
    Mode,
    TeacherState,
    all_topics_completed,
    initial_state,
    make_checkpointer,
    to_response,
)
from agent.summary import after_back_to_lecture, back_to_lecture, can_summarize, make_summary_node


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
    if kind == "summary":
        return can_summarize(state)
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
    if state["event"]["type"] == "continue" and state["mode"] == Mode.SUMMARIZING:
        return "back_to_lecture"
    return {
        "continue": "continue",
        "answer": "take_answer",
        "raise_hand": "raise_hand",
        "question": "take_question",
        "go_to_topic": "go_to_topic",
        "repeat": "choose_repeat",
        "summary": "summary",
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
    graph.add_node("summary", make_summary_node(llm))
    graph.add_node("back_to_lecture", back_to_lecture)

    # Waiting, and handling events
    graph.add_node("wait", wait)
    graph.add_node("continue", continue_lecture)
    graph.add_node("finish_intro", finish_intro)
    graph.add_node("take_answer", take_input)
    graph.add_node("take_question", take_input)
    graph.add_node("raise_hand", handle_raise_hand)
    graph.add_node("go_to_topic", handle_go_to_topic)
    graph.add_node("choose_repeat", handle_choose_repeat)

    # Start of a session: planning returns the intro. Do NOT enter explain yet,
    # because no topic has been selected at this point.
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "wait")

    # From wait, by event
    graph.add_conditional_edges(
        "wait",
        route_event,
        [
            "continue", "take_answer", "raise_hand", "take_question",
            "go_to_topic", "choose_repeat", "summary", "back_to_lecture",
        ],
    )
    graph.add_conditional_edges(
        "continue",
        after_continue,
        ["finish_intro", "ask_question", "explain", "next_topic"],
    )
    graph.add_edge("finish_intro", "wait")
    graph.add_conditional_edges("next_topic", after_next_topic, ["explain", "wait", "closing"])
    graph.add_edge("take_answer", "evaluate_answer")
    graph.add_edge("take_question", "answer_student_question")
    graph.add_conditional_edges("go_to_topic", after_entering_topic, ["explain", "wait", "closing"])
    graph.add_edge("choose_repeat", "repeat")
    graph.add_conditional_edges("back_to_lecture", after_back_to_lecture, ["explain", "wait", "next_topic"])

    # Everything that speaks goes back to waiting
    for node in [
        "explain", "ask_question", "evaluate_answer", "answer_student_question",
        "raise_hand", "repeat", "closing", "summary",
    ]:
        graph.add_edge(node, "wait")

    return graph.compile(checkpointer=checkpointer or make_checkpointer())


# ---------------------------------------------------------------------------
# What the FastAPI routes call
# ---------------------------------------------------------------------------


class Teacher:
    """The teacher agent. Create one and share it across requests."""

    def __init__(self, llm: LLM | None = None, checkpointer=None, rng: random.Random | None = None):
        self.llm = llm or get_llm()
        self.checkpointer = checkpointer or make_checkpointer()
        self.graph = build_graph(self.llm, self.checkpointer)
        self.quizzes: dict[str, QuizRecord] = {}  # each session's current quiz
        self.quiz_lock = threading.Lock()
        self.rng = rng or random.Random()

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
        with self.quiz_lock:
            self.quizzes.pop(session_id, None)

    def start_quiz(self, session_id: str, mode: str = "new") -> Quiz:
        """The quiz item in the outline: "new" questions, or "restart" the same ones.

        Raises SessionNotFound, or EventNotAllowed before every topic is completed.
        """
        state = self._state(session_id)
        if not all_topics_completed(state):
            raise EventNotAllowed("The quiz unlocks once every topic is completed")
        with self.quiz_lock:
            previous = self.quizzes.get(session_id)
        if mode == "restart" and previous is not None:
            record = restart_quiz(previous)
        else:
            record = new_quiz(self.llm, state, previous, self.rng)  # LLM call, outside the lock
        with self.quiz_lock:
            self.quizzes[session_id] = record
        return to_quiz(session_id, record, state["outline"])

    def submit_quiz(self, session_id: str, answers: list[int | str | None]) -> QuizResult:
        """Mark the quiz: score, the right answers, and topics to improve on.

        Typed answers are graded by the LLM (one call). Raises SessionNotFound,
        or EventNotAllowed if there's no quiz or the answers don't fit the questions.
        """
        state = self._state(session_id)
        with self.quiz_lock:
            record = self.quizzes.get(session_id)
        if record is None:
            raise EventNotAllowed("There's no quiz to submit")
        problem = answers_problem(record, answers)
        if problem:
            raise EventNotAllowed(problem)
        return mark_quiz(self.llm, session_id, record, answers, state["outline"])  # LLM call, outside the lock

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
