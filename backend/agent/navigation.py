"""Step 10: clicking topics in the outline, repeat, continue, and the end.

The outline is on the same page as the lecture, so the student can use it
at any time during the lecture:
- click a topic's name: a topic left halfway resumes where they left it; a
  finished topic (or the one they're in) is explained again the same way; a
  topic not reached yet is taught;
- repeat button on a topic they've been taught: Regina explains it again,
  differently (a new explanation from the LLM).
Ending the session is handled by Teacher.end_session(): it deletes everything.

"continue" is not a button: the frontend sends it automatically when the
speech has finished playing. Where it leads, by what was just said:
    EXPLAINING         -> ask a question about that part
    FEEDBACK           -> next part of the topic, or wait at the outline
    ANSWERING_STUDENT  -> back to the explanation, from the interrupted segment
    SUMMARIZING        -> back to where the student was (see summary.py)
After a topic finishes, Regina waits for the student to choose another topic.

Each action has a check (can the student do it right now?). Step 11 rejects
an action when its check says no.
"""

from agent.explaining import (
    add_slide_transitions,
    enter_topic,
    generate_explanation,
    next_stop,
    save_progress,
    say_part,
)
from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.questioning import topic_finished
from agent.state import Mode, TeacherState

# ---------------------------------------------------------------------------
# Clicking a topic's name
# ---------------------------------------------------------------------------


def can_go_to_topic(state: TeacherState, topic_index: int) -> bool:
    # Also after the lecture has ended, so topics can be replayed around the quiz.
    return 0 <= topic_index < len(state["outline"])


def go_to_topic(state: TeacherState, topic_index: int) -> dict:
    """Switch to a topic, saving where the student was in the current one.

    A waiting question (or a raised hand) is dropped.
    """
    return enter_topic(state, topic_index, save_progress(state))


def after_entering_topic(state: TeacherState) -> str:
    """A topic never started still needs explaining; a saved one is already set up."""
    if state["current_topic"] is None:
        return "closing"
    return "explain" if not state["segments"] else "wait"


# ---------------------------------------------------------------------------
# Repeat button
# ---------------------------------------------------------------------------


def taught_topics(state: TeacherState) -> set[int]:
    taught = set(state["completed_topics"]) | set(state["topic_progress"])
    if state["current_topic"] is not None and state["segments"]:
        taught.add(state["current_topic"])
    return taught


def can_repeat(state: TeacherState, topic_index: int) -> bool:
    """For topics the student has been taught (finished, left halfway, or current)."""
    return topic_index in taught_topics(state)


def choose_topic_to_repeat(state: TeacherState, topic_index: int) -> dict:
    """Make the topic current, with its old explanation in `segments` for the repeat node."""
    progress = save_progress(state)
    return {
        "current_topic": topic_index,
        "topic_progress": progress,
        "segments": progress.get(topic_index, {}).get("segments", []),
        "pending_question": None,
        "attempts": 0,
    }


def make_repeat_node(llm: LLM):
    """The 'repeat' node: explains the current topic again, differently, from the start.

    `segments` holds the old explanation (set by choose_topic_to_repeat), so
    the LLM can avoid repeating it. A waiting question is dropped.
    """

    def repeat(state: TeacherState) -> dict:
        segments, points, pace = generate_explanation(llm, state, previous=state["segments"])
        segments, points, segment_slides = add_slide_transitions(
            segments,
            points,
            state["outline"][state["current_topic"]]["source_slides"],
        )
        return {
            "pending_question": None,
            "attempts": 0,
            "pace": pace,
            **say_part(
                segments,
                points,
                0,
                segment_slides,
            ),
        }

    return repeat


# ---------------------------------------------------------------------------
# Continue (the current speech finished playing)
# ---------------------------------------------------------------------------

CONTINUABLE = {
    Mode.INTRO,
    Mode.EXPLAINING,
    Mode.FEEDBACK,
    Mode.ANSWERING_STUDENT,
    Mode.SUMMARIZING,
}


def can_continue(state: TeacherState) -> bool:
    return state["mode"] in CONTINUABLE


def continue_lecture(state: TeacherState) -> dict:
    """State change when the student presses continue."""
    if state["mode"] == Mode.EXPLAINING:
        # The part has been said: move to the end of it, where its question goes.
        stop = next_stop(state["segment_index"], state["question_points"], len(state["segments"]))
        return {"segment_index": stop}
    return {}


def after_continue(state: TeacherState) -> str:
    """Which node runs after continue_lecture: 'ask_question', 'explain' or 'next_topic'."""
    if state["mode"] == Mode.INTRO:
        return "finish_intro"
    if state["mode"] == Mode.EXPLAINING:
        return "ask_question"
    if state["mode"] == Mode.FEEDBACK and topic_finished(state):
        return "next_topic"
    return "explain"


def after_next_topic(state: TeacherState) -> str:
    """After a topic is done, wait for the student to choose from the outline."""
    return "wait"


def finish_intro(state: TeacherState) -> dict:
    return {
        "speech": [],
        "mode": Mode.WAITING_TOPIC,
        "current_topic": None,
        "segments": [],
        "segment_slides": [],
        "segment_index": 0,
        "question_points": [],
        "pending_question": None,
        "speech_slides": [],
    }


# ---------------------------------------------------------------------------
# End of the lecture
# ---------------------------------------------------------------------------


def closing_prompt(state: TeacherState) -> str:
    """A short lecture-complete note that prepares the student for the quiz."""
    outline = state["outline"]
    to_review = [outline[i]["title"] for i in state["topics_to_improve"] if i < len(outline)]
    lines = [
        "The lecture is finished. In 1 to 3 spoken sentences, say that the quiz is next "
        "and encourage the student to collect the key ideas. Do not say goodbye."
    ]
    if to_review:
        lines.append(
            "The student made mistakes on questions about: " + ", ".join(to_review) + ". "
            "Name these topics and encourage them to review them."
        )
    lines.append("Don't recap the lecture, and don't praise specific topics or mention scores.")
    return "\n".join(lines)


def fallback_closing(state: TeacherState) -> str:
    text = "You have reached the end of the lecture. "
    to_review = [state["outline"][i]["title"] for i in state["topics_to_improve"]]
    if to_review:
        text += f"It's worth reviewing {', '.join(to_review)}. "
    return text + "Take a moment to collect the key ideas; the quiz is next."


def make_closing_node(llm: LLM):
    """The 'closing' node: wrap up the lecture and point toward the quiz."""

    def closing(state: TeacherState) -> dict:
        personality = get_personality(state["environment"])
        try:
            text = llm.chat(messages(build_system_prompt(personality), closing_prompt(state)))
        except LLMError:
            text = fallback_closing(state)
        return {
            "speech": [text],
            "mode": Mode.ENDED,
            "current_topic": None,
            "pending_question": None,
            "history": [{"role": "teacher", "text": text}],
        }

    return closing
