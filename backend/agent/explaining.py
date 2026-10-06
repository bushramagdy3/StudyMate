"""Step 7: Regina explains the current topic, in short spoken segments.

A topic's explanation is written once, as `segments_per_topic` segments, and
delivered in parts: each part ends where the teacher asks a question. The LLM
chooses where the questions go (after a complete idea), e.g. for 4 segments
and 2 questions it might choose question_points = [1, 4]:

    [0] -> question -> [1, 2, 3] -> question

While a part is playing, state["segment_index"] is the index of its FIRST
segment. The frontend reports positions inside the part it received, so:
- raise_hand(segment_index=i)  -> resume from state["segment_index"] + i
- continue                     -> move on to next_stop(...)
"""

from pydantic import BaseModel, Field

from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.planning import slides_text
from agent.state import Mode, OutlineTopic, TeacherState

RECENT_HISTORY = 6  # how many recent lines of conversation to show the LLM


class Explanation(BaseModel):
    segments: list[str]
    question_after: list[int] = Field(
        description="Segment numbers (1 = first segment) after which to pause and ask a question"
    )


# ---------------------------------------------------------------------------
# Where the questions go
# ---------------------------------------------------------------------------


def question_count(segment_count: int, questions_per_topic: int) -> int:
    return max(1, min(questions_per_topic, segment_count))


def default_question_points(segment_count: int, questions_per_topic: int) -> list[int]:
    """Questions spread evenly, the last one at the end. Used when the LLM's choice is unusable.

    default_question_points(4, 2) == [2, 4]   default_question_points(3, 1) == [3]
    """
    questions = question_count(segment_count, questions_per_topic)
    points = {round(segment_count * k / questions) for k in range(1, questions + 1)}
    return sorted(point for point in points if point > 0)


def choose_question_points(proposed: list[int], segment_count: int, questions_per_topic: int) -> list[int]:
    """Use the LLM's question positions if they're valid, otherwise the default ones.

    Valid means: the personality's number of questions, real segment numbers,
    no duplicates, and the last question at the end of the topic.
    """
    points = sorted(set(proposed))
    valid = (
        len(points) == question_count(segment_count, questions_per_topic)
        and all(1 <= point <= segment_count for point in points)
        and len(points) == len(proposed)
        and points[-1] == segment_count
    )
    return points if valid else default_question_points(segment_count, questions_per_topic)


def next_stop(segment_index: int, question_points: list[int], segment_count: int) -> int:
    """Where the part starting at segment_index ends (exclusive): the next question point."""
    for point in question_points:
        if point > segment_index:
            return point
    return segment_count


# ---------------------------------------------------------------------------
# Writing the explanation
# ---------------------------------------------------------------------------


def explain_prompt(state: TeacherState, previous: list[str] | None = None) -> str:
    personality = get_personality(state["environment"])
    index = state["current_topic"]
    topic = state["outline"][index]
    count = personality.segments_per_topic
    questions = question_count(count, personality.questions_per_topic)
    covered = [state["outline"][i]["title"] for i in state["completed_topics"] if i != index]

    lines = [
        f'Explain topic {index + 1} of {len(state["outline"])}: "{topic["title"]}".',
        f"Goal: {topic['summary']}" if topic["summary"] else "",
        "Key points to cover:" if topic["key_points"] else "",
        *(f"- {point}" for point in topic["key_points"]),
        "",
        "Teach it from these lecture slides:",
        slides_text(state["lecture"], topic["source_slides"]) or "(no slide text; use the key points)",
        "",
    ]

    if not state["history"] and previous is None:
        lines.append(
            "This is the very start of the lecture: begin the first segment by greeting "
            "the student, introducing yourself by name, and saying what today's lecture is about."
        )
    elif covered:
        lines.append(
            f"Already covered: {', '.join(covered)}. Don't re-teach these, but you can "
            "briefly connect to the previous topic."
        )

    if previous is not None:
        lines += ["", "The student asked to hear this topic explained again."]
        if previous:
            lines += ["Your previous explanation was:", *(f'"{segment}"' for segment in previous)]
        lines += [
            "Explain it again differently: use simpler words, a new example or analogy, "
            "and smaller steps. Don't repeat the same sentences.",
        ]

    recent = state["history"][-RECENT_HISTORY:]
    if recent:
        lines += ["", "Recent conversation, for context:"]
        lines += [f"{line['role'].capitalize()}: {line['text']}" for line in recent]

    lines += [
        "",
        f"Write the explanation as exactly {count} segments, in teaching order.",
        "Each segment is 2 to 4 spoken sentences about one small idea.",
        "Don't ask the student questions; questions come separately.",
        "",
        f"Also choose where to pause and ask the student a question: in question_after, list "
        f"exactly {questions} segment number(s) between 1 and {count}, each right after a "
        f"complete idea has been explained. The last one must be {count} (the end of the topic).",
        "Don't mention segments, slide numbers or these instructions.",
    ]
    return "\n".join(lines)


def generate_segments(
    llm: LLM, state: TeacherState, previous: list[str] | None = None
) -> tuple[list[str], list[int]]:
    """The current topic's explanation as (segments, question_points).

    `previous` is set when the student asked to hear the topic again (repeat):
    the old explanation, or [] if it's no longer available.
    """
    personality = get_personality(state["environment"])
    topic = state["outline"][state["current_topic"]]
    try:
        explanation = llm.chat_json(
            messages(build_system_prompt(personality), explain_prompt(state, previous)),
            Explanation,
            temperature=0.7,
        )
        segments = fit_segments(explanation.segments, personality.segments_per_topic)
        if segments:
            points = choose_question_points(
                explanation.question_after, len(segments), personality.questions_per_topic
            )
            return segments, points
    except LLMError:
        pass
    segments = fallback_segments(topic)
    return segments, default_question_points(len(segments), personality.questions_per_topic)


def fit_segments(segments: list[str], count: int) -> list[str]:
    """Drop empty segments; if there are too many, merge the extras into the last one."""
    segments = [segment.strip() for segment in segments if segment.strip()]
    if len(segments) > count:
        segments = segments[: count - 1] + [" ".join(segments[count - 1 :])]
    return segments


def fallback_segments(topic: OutlineTopic) -> list[str]:
    """A plain explanation from the outline, if the LLM can't be reached."""
    segments = [f"Let's look at {topic['title']}. {topic['summary']}".strip()]
    segments += [point if point.endswith(".") else point + "." for point in topic["key_points"]]
    return segments


# ---------------------------------------------------------------------------
# The LangGraph node
# ---------------------------------------------------------------------------


def make_explain_node(llm: LLM):
    """The 'explain' node: says the next part of the current topic's explanation.

    New topic (no segments yet): writes the explanation first and starts at segment 0.
    Otherwise: continues from state["segment_index"], e.g. after a question or a raised hand.
    """

    def explain(state: TeacherState) -> dict:
        if not state["segments"]:
            segments, points = generate_segments(llm, state)
            return say_part(segments, points, 0)
        return say_part(state["segments"], state["question_points"], state["segment_index"])

    return explain


def say_part(segments: list[str], points: list[int], segment_index: int) -> dict:
    """State update that says the part of the explanation starting at segment_index."""
    segment_index = min(segment_index, len(segments) - 1)
    speech = segments[segment_index : next_stop(segment_index, points, len(segments))]
    return {
        "segments": segments,
        "question_points": points,
        "segment_index": segment_index,
        "speech": speech,
        "mode": Mode.EXPLAINING,
        "history": [{"role": "teacher", "text": " ".join(speech)}],
    }


# ---------------------------------------------------------------------------
# Remembering each topic (for clicking topics in the outline)
# ---------------------------------------------------------------------------


def resume_index(state: TeacherState) -> int:
    """Where to pick the current topic up again later.

    During a question, go back to the start of the part it's about, so the
    student hears that part again and then gets the question.
    """
    if state["mode"] == Mode.AWAITING_ANSWER:
        return max((p for p in state["question_points"] if p < state["segment_index"]), default=0)
    return state["segment_index"]


def save_progress(state: TeacherState) -> dict:
    """topic_progress, with the current topic's explanation and position saved."""
    progress = dict(state["topic_progress"])
    topic = state["current_topic"]
    if topic is not None and state["segments"]:
        progress[topic] = {
            "segments": state["segments"],
            "question_points": state["question_points"],
            "segment_index": resume_index(state),
        }
    return progress


def enter_topic(state: TeacherState, topic: int, progress: dict) -> dict:
    """State update that makes `topic` the current one.

    - never started: segments are cleared, so the explain node writes them;
    - left halfway: resumes where the student left it;
    - finished (or it's the topic they're in): from the start, same explanation.
    """
    update = {
        "current_topic": topic,
        "topic_progress": progress,
        "pending_question": None,
        "attempts": 0,
    }
    saved = progress.get(topic)
    if saved is None:
        return update | {"segments": [], "question_points": [], "segment_index": 0}

    start = saved["segment_index"]
    finished = topic in state["completed_topics"] or start >= len(saved["segments"])
    if finished or topic == state["current_topic"]:
        start = 0
    return update | say_part(saved["segments"], saved["question_points"], start)
