"""The contract between the AI teacher agent and the rest of StudyMate.

Everything that goes into or comes out of the teacher agent is defined here.
The PDF extraction, the FastAPI routes and the React frontend should only
rely on these models, so each part can be built independently.

Conventions:
- Topic indexes are 0-based (the first topic is 0).
- Slide numbers are 1-based, matching what the student sees in the PDF.
"""

from enum import Enum
from typing import Annotated, Literal, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator


class _Model(BaseModel):
    # Trim stray whitespace from typed input and reject unknown fields,
    # so typos in the frontend's JSON fail loudly instead of being ignored.
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class Environment(str, Enum):
    """The learning environment the student picks. It sets the personality."""

    LECTURE_HALL = "lecture_hall"  # professor
    STUDY_ROOM = "study_room"  # tutor
    CAFE = "cafe"  # study friend


class LectureChunk(_Model):
    """The extracted text of one slide or page of the lecture PDF."""

    slide: int = Field(ge=1)
    text: str


class StartSessionRequest(_Model):
    """Everything the agent needs to plan and start a new lecture."""

    environment: Environment
    lecture: list[LectureChunk] = Field(min_length=1)


# Student events: each one is something the student did during the lecture.
# The "type" field tells them apart, e.g. {"type": "answer", "text": "..."}.


class AnswerEvent(_Model):
    """The student's typed answer to the question the teacher asked."""

    type: Literal["answer"] = "answer"
    text: str = Field(min_length=1)


class RaiseHandEvent(_Model):
    """The student raised their hand while the teacher was speaking.

    segment_index is the speech segment the frontend was playing when the
    hand went up, so the lecture can resume exactly from there.
    """

    type: Literal["raise_hand"] = "raise_hand"
    segment_index: int = Field(ge=0)


class QuestionEvent(_Model):
    """The question the student typed after raising their hand."""

    type: Literal["question"] = "question"
    text: str = Field(min_length=1)


class RepeatEvent(_Model):
    """Repeat button on a topic in the outline: explain it again, in a different way."""

    type: Literal["repeat"] = "repeat"
    topic_index: int = Field(ge=0)


class SummaryEvent(_Model):
    """The student clicked "Summary" at the top of the outline (private tutor only).

    Regina summarises the whole lecture, then the lecture continues where they were.
    """

    type: Literal["summary"] = "summary"


class GoToTopicEvent(_Model):
    """The student clicked a topic's name in the outline.

    A topic left halfway resumes where they left it; a finished topic (or the
    one they're in) is explained again the same way; a new one is taught.
    """

    type: Literal["go_to_topic"] = "go_to_topic"
    topic_index: int = Field(ge=0)


class ContinueEvent(_Model):
    """Sent AUTOMATICALLY by the frontend when the speech finished playing (not a button)."""

    type: Literal["continue"] = "continue"


StudentEvent = Annotated[
    Union[
        AnswerEvent,
        RaiseHandEvent,
        QuestionEvent,
        RepeatEvent,
        SummaryEvent,
        GoToTopicEvent,
        ContinueEvent,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


class AvatarState(str, Enum):
    """What the 2D avatar should be doing."""

    IDLE = "idle"
    SPEAKING = "speaking"
    LISTENING = "listening"
    THINKING = "thinking"
    ASKING_QUESTION = "asking_question"


class Awaiting(str, Enum):
    """What the frontend should let the student do next."""

    NOTHING = "nothing"  # lecture finished (after the goodbye), no input expected
    ANSWER = "answer"  # show the answer box
    QUESTION = "question"  # hand is raised, show the question box
    CONTINUE = "continue"  # after the speech plays, automatically send a "continue" event


class Topic(_Model):
    """One entry in the lecture outline."""

    index: int = Field(ge=0)
    title: str
    summary: str = ""


class LectureSummarySection(_Model):
    """One scannable section in the private tutor's revision recap."""

    heading: str
    points: list[str] = Field(min_length=1, max_length=3)


class TeacherResponse(_Model):
    """What the agent returns after every turn."""

    session_id: str
    # The teacher's speech, split into short segments. The frontend sends
    # each one to TTS and plays them in order. Splitting lets the agent know
    # where it was if the student raises their hand.
    speech: list[str]
    # The slide to show as each speech item starts. This is only populated for
    # explanations; other teacher turns keep the current slide on screen.
    speech_slides: list[int] = Field(default_factory=list)
    avatar_state: AvatarState
    awaiting: Awaiting
    phase: str = ""
    outline: list[Topic]
    # A concise, sectioned revision recap of the whole lecture.
    lecture_summary: list[LectureSummarySection] = Field(default_factory=list)
    current_topic: int | None = None  # None before planning or after the end
    current_slide: int | None = None  # The PDF slide/page currently being explained
    completed_topics: list[int] = Field(default_factory=list)
    started_topics: list[int] = Field(default_factory=list)
    # Only true while the teacher is explaining: show the raise-hand button then.
    can_raise_hand: bool = False
    # Show "Summary" at the top of the outline (only the private tutor has it).
    summary_available: bool = False
    # The quiz at the bottom of the outline unlocks once every topic is completed.
    quiz_available: bool = False
    # How far through the lecture the student is, 0.0 to 1.0: finished topics
    # count fully, and the topic in progress counts by how much has been said.
    lecture_progress: float = Field(default=0.0, ge=0.0, le=1.0)
    # Playback speed for this speech (1.0 = normal). Regina slows down for deep
    # or brand-new concepts and goes a little faster on intuitive ones.
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)

    @model_validator(mode="after")
    def _topics_exist(self) -> "TeacherResponse":
        valid = range(len(self.outline))
        if self.current_topic is not None and self.current_topic not in valid:
            raise ValueError(f"current_topic {self.current_topic} is not in the outline")
        missing = [i for i in self.completed_topics if i not in valid]
        if missing:
            raise ValueError(f"completed_topics {missing} are not in the outline")
        if self.speech_slides and len(self.speech_slides) != len(self.speech):
            raise ValueError("speech_slides must match the number of speech segments")
        return self


# ---------------------------------------------------------------------------
# The agent's interface
# ---------------------------------------------------------------------------


class TeacherAgent(Protocol):
    """The two calls the FastAPI backend makes into the teacher agent."""

    def start_session(self, request: StartSessionRequest) -> TeacherResponse:
        """Plan the lecture, start teaching and return the first turn."""
        ...

    def send_event(self, session_id: str, event: StudentEvent) -> TeacherResponse:
        """Handle one student action and return the teacher's next turn."""
        ...


# ---------------------------------------------------------------------------
# The mini quiz (after every topic is completed)
# ---------------------------------------------------------------------------


class QuizRequest(_Model):
    """The quiz item in the outline.

    "new": write a new quiz. It focuses on the topics the student got wrong
    (in the last quiz, or during the lecture for the first quiz), plus a few
    questions on the other topics; with no mistakes it's balanced.
    "restart": the same questions again, from the start.
    """

    mode: Literal["new", "restart"] = "new"


QuestionKind = Literal["mcq", "text"]  # multiple choice, or a typed answer


class QuizQuestion(_Model):
    """One question, as the student sees it (no answer in it).

    "mcq": pick one of `options`. "text": type the answer (`options` is empty);
    `code_answer` means the answer is code, so show a code-style box.
    """

    index: int = Field(ge=0)
    topic_index: int = Field(ge=0)
    topic_title: str
    kind: QuestionKind = "mcq"
    question: str
    options: list[str] = Field(default_factory=list, max_length=4)
    code_answer: bool = False

    @model_validator(mode="after")
    def _options_match_kind(self) -> "QuizQuestion":
        if self.kind == "mcq" and len(self.options) < 2:
            raise ValueError("a multiple-choice question needs at least 2 options")
        if self.kind == "text" and self.options:
            raise ValueError("a typed-answer question has no options")
        return self


class Quiz(_Model):
    session_id: str
    attempt: int = Field(ge=1)  # 1 for the first quiz, +1 for each new or restarted one
    questions: list[QuizQuestion] = Field(min_length=1)
    # The topics this quiz concentrates on (empty when it's balanced).
    focus_topics: list[Topic] = Field(default_factory=list)
    # Why the LLM chose this mix of question kinds for this lecture, e.g.
    # "Mostly typed answers: code is best tested by writing it."
    style_note: str = ""


class QuizAnswers(_Model):
    """One answer per question, in order: the option index for "mcq", the typed
    text for "text", or null if left blank."""

    # Keep a typed value such as "1" as text. It must not be coerced into an
    # option index before the quiz checker sees the question kind.
    answers: list[StrictInt | StrictStr | None]


class QuizReview(_Model):
    """How one question went, shown in the results."""

    index: int = Field(ge=0)
    topic_index: int = Field(ge=0)
    kind: QuestionKind = "mcq"
    question: str
    options: list[str] = Field(default_factory=list)
    code_answer: bool = False
    chosen_index: int | None = None  # "mcq": the option picked
    correct_index: int | None = None  # "mcq": the right option
    answer_text: str | None = None  # "text": what the student typed
    expected_answer: str = ""  # "text": a model answer
    correct: bool
    feedback: str = ""  # "text": one line on what was right or missing
    explanation: str


class QuizResult(_Model):
    session_id: str
    score: int = Field(ge=0)  # correct answers
    total: int = Field(ge=1)
    review: list[QuizReview]
    # Topics with at least one wrong answer; empty when everything was right.
    topics_to_improve: list[Topic] = Field(default_factory=list)
    feedback: str  # one or two sentences from Regina

