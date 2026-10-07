"""The teacher agent's state: everything it remembers during one lecture.

LangGraph saves this after every step (keyed by session_id as the thread_id),
so it is also everything that survives between two API calls.
"""

import operator
from enum import Enum
from typing import Annotated, Literal, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from agent.contract import (
    Awaiting,
    AvatarState,
    Environment,
    LectureChunk,
    StartSessionRequest,
    TeacherResponse,
    Topic,
)
from agent.personalities import get_personality

# How many tries the student gets per question: one answer plus one retry.
MAX_ATTEMPTS = 2


class Mode(str, Enum):
    """What the agent is waiting for while it is paused."""

    INTRO = "intro"  # opening/title-slide moment is playing
    WAITING_TOPIC = "waiting_topic"  # intro or a topic finished; waiting for outline click
    EXPLAINING = "explaining"  # an explanation part is playing; continue -> ask a question
    FEEDBACK = "feedback"  # praise or the revealed answer is playing; continue -> lecture goes on
    AWAITING_ANSWER = "awaiting_answer"  # asked a question; waiting for the student's answer
    AWAITING_STUDENT_QUESTION = "awaiting_student_question"  # hand raised; waiting for their question
    SUMMARIZING = "summarizing"  # the lecture summary is playing; continue -> back to the lecture
    ANSWERING_STUDENT = "answering_student"  # answer to their question is playing; continue -> back to the explanation
    ENDED = "ended"


class OutlineTopic(TypedDict):
    """One topic of the lecture plan (created in Step 6)."""

    title: str
    summary: str  # what the student should understand after this topic
    key_points: list[str]
    source_slides: list[int]  # which slides to teach it from


class PendingQuestion(TypedDict):
    """The question the teacher asked and is waiting on.

    The expected answer and explanation are generated together with the
    question, so grading, the hint, the praise and the reveal all agree.
    """

    question: str
    expected_answer: str
    explanation: str  # the short "why" used after praise or after revealing the answer


class TopicProgress(TypedDict):
    segments: list[str]
    segment_slides: list[int]
    question_points: list[int]
    segment_index: int  # where to pick the topic up again


class Message(TypedDict):
    """One line of conversation, used as short memory in prompts."""

    role: Literal["teacher", "student"]
    text: str


class TeacherState(TypedDict):
    # --- set once at the start ---
    session_id: str
    environment: Environment  # picks the personality (Step 4)
    lecture: list[LectureChunk]
    outline: list[OutlineTopic]

    # --- where we are in the lecture ---
    current_topic: int | None  # None until the outline exists, and after the end
    current_slide: int | None
    segments: list[str]  # the current topic's explanation, split into short parts
    segment_slides: list[int]  # slide/page to show for each explanation segment
    segment_index: int  # next segment to say; on raise_hand, the one to resume from
    question_points: list[int]  # ask a question after these segment numbers, e.g. [2, 4]
    completed_topics: list[int]
    # Each topic's explanation and where the student got to, so clicking a
    # topic in the outline can resume it or replay it the same way.
    topic_progress: dict[int, TopicProgress]

    # --- what we are doing right now ---
    mode: Mode
    pending_question: PendingQuestion | None
    attempts: int  # wrong answers so far to pending_question
    student_input: str | None  # latest answer or question the student typed
    event: dict | None  # the student event being handled right now (Step 11)

    # --- output of the current turn ---
    speech: list[str]  # what the teacher says now; replaced every turn
    speech_slides: list[int]  # slides paired with the current explanation speech

    # --- memory ---
    history: Annotated[list[Message], operator.add]  # appended to, never replaced
    topics_to_improve: list[int]  # topics with any wrong answer (even if right on the retry)
    summary: list[str]  # the lecture summary, once written (reused on later clicks)


def initial_state(session_id: str, request: StartSessionRequest) -> TeacherState:
    """The state of a brand-new session, before the lecture is planned."""
    return {
        "session_id": session_id,
        "environment": request.environment,
        "lecture": request.lecture,
        "outline": [],
        "current_topic": None,
        "current_slide": request.lecture[0].slide if request.lecture else None,
        "segments": [],
        "segment_slides": [],
        "segment_index": 0,
        "question_points": [],
        "completed_topics": [],
        "mode": Mode.EXPLAINING,
        "pending_question": None,
        "attempts": 0,
        "student_input": None,
        "event": None,
        "topic_progress": {},
        "speech": [],
        "speech_slides": [],
        "history": [],
        "topics_to_improve": [],
        "summary": [],
    }


FeedbackKind = Literal["praise", "hint", "reveal"]


def feedback_kind(correct: bool, attempts: int) -> FeedbackKind:
    """Decide how to respond to an answer.

    attempts is the number of wrong answers BEFORE this one.
    - correct (first try or retry)      -> praise + short explanation
    - wrong, and a retry is left        -> hint, ask again
    - wrong on the last try             -> reveal the answer + explanation
    """
    if correct:
        return "praise"
    if attempts + 1 < MAX_ATTEMPTS:
        return "hint"
    return "reveal"


# How each mode looks to the frontend: (avatar_state, awaiting).
_MODE_TO_UI = {
    Mode.INTRO: (AvatarState.SPEAKING, Awaiting.CONTINUE),
    Mode.WAITING_TOPIC: (AvatarState.IDLE, Awaiting.NOTHING),
    Mode.EXPLAINING: (AvatarState.SPEAKING, Awaiting.CONTINUE),
    Mode.FEEDBACK: (AvatarState.SPEAKING, Awaiting.CONTINUE),
    Mode.ANSWERING_STUDENT: (AvatarState.SPEAKING, Awaiting.CONTINUE),
    Mode.SUMMARIZING: (AvatarState.SPEAKING, Awaiting.CONTINUE),
    Mode.AWAITING_ANSWER: (AvatarState.ASKING_QUESTION, Awaiting.ANSWER),
    Mode.AWAITING_STUDENT_QUESTION: (AvatarState.LISTENING, Awaiting.QUESTION),
    Mode.ENDED: (AvatarState.IDLE, Awaiting.NOTHING),
}


def to_response(state: TeacherState) -> TeacherResponse:
    """Turn the internal state into the TeacherResponse the frontend gets."""
    avatar_state, awaiting = _MODE_TO_UI[state["mode"]]
    if state["speech"] and state["mode"] in (Mode.WAITING_TOPIC, Mode.ENDED):
        avatar_state = AvatarState.SPEAKING
    started_topics = sorted(
        set(state["completed_topics"])
        | set(state["topic_progress"])
        | (
            {state["current_topic"]}
            if state["current_topic"] is not None and state["segments"]
            else set()
        )
    )

    speech_slides = (
        state["speech_slides"]
        if state["mode"] == Mode.EXPLAINING
        and len(state["speech_slides"]) == len(state["speech"])
        else []
    )

    return TeacherResponse(
        session_id=state["session_id"],
        speech=state["speech"],
        speech_slides=speech_slides,
        avatar_state=avatar_state,
        awaiting=awaiting,
        phase=state["mode"].value,
        outline=[
            Topic(index=i, title=t["title"], summary=t["summary"])
            for i, t in enumerate(state["outline"])
        ],
        current_topic=state["current_topic"],
        current_slide=state["current_slide"],
        completed_topics=state["completed_topics"],
        started_topics=started_topics,
        can_raise_hand=state["mode"] == Mode.EXPLAINING,
        summary_available=get_personality(state["environment"]).offers_summary
        and state["mode"] != Mode.ENDED,
    )


# Our own types that are stored in the state. LangGraph only reloads saved
# types it has been told are safe, so they're listed here.
SAVED_TYPES = [
    ("agent.contract", "Environment"),
    ("agent.contract", "LectureChunk"),
    ("agent.state", "Mode"),
]


def make_checkpointer() -> MemorySaver:
    """The save system for sessions (Step 2's MemorySaver), allowing our types."""
    return MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=SAVED_TYPES))
