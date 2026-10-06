"""Step 10: leaving to the outline, repeat, go to a topic, continue, and the end.

During a lecture the student has one button, "back": it saves exactly where
they are and shows the outline page. From the outline they can:
- go to a topic: resumes exactly where they left if it's the topic in
  progress, otherwise teaches that topic from the start;
- repeat a topic they've already been taught (or the one in progress):
  Regina explains it again, differently.

"continue" is not a button: the frontend sends it automatically when the
speech has finished playing. Where it leads, by what was just said:
    EXPLAINING         -> ask a question about that part
    FEEDBACK           -> next part of the topic, or the next topic
    ANSWERING_STUDENT  -> back to the explanation, from the interrupted segment
After the last topic, the lecture ends with a goodbye summary.

Each action has a check (can the student do it right now?). Step 11 wires
them into the graph and ignores an action when its check says no.
"""

from agent.explaining import generate_segments, next_stop, say_part
from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.questioning import topic_finished
from agent.state import Mode, TeacherState

# ---------------------------------------------------------------------------
# Back (leave the lecture for the outline page)
# ---------------------------------------------------------------------------


def can_go_back(state: TeacherState) -> bool:
    return state["mode"] not in (Mode.PAUSED, Mode.ENDED)


def go_back(state: TeacherState, segment_index: int = 0) -> dict:
    """Pause the lecture and remember exactly where the student was.

    segment_index is the position in the speech that was playing; during an
    explanation, the lecture resumes from that segment.
    """
    update = {
        "mode": Mode.PAUSED,
        "paused_mode": state["mode"],
        "paused_speech": state["speech"],
        "speech": [],
    }
    if state["mode"] == Mode.EXPLAINING:
        start = state["segment_index"]
        part_end = next_stop(start, state["question_points"], len(state["segments"]))
        update["segment_index"] = max(start, min(start + segment_index, part_end - 1))
    return update


def resume(state: TeacherState) -> dict:
    """Continue exactly where the student pressed back."""
    if state["paused_mode"] == Mode.EXPLAINING:
        update = say_part(state["segments"], state["question_points"], state["segment_index"])
        update.pop("history")  # it was already said once
    else:
        update = {"mode": state["paused_mode"], "speech": state["paused_speech"]}
    return update | {"paused_mode": None, "paused_speech": []}


# ---------------------------------------------------------------------------
# Go to a topic (from the outline)
# ---------------------------------------------------------------------------


def can_go_to_topic(state: TeacherState, topic_index: int) -> bool:
    return state["mode"] == Mode.PAUSED and 0 <= topic_index < len(state["outline"])


def go_to_topic(state: TeacherState, topic_index: int) -> dict:
    """From the outline: resume the topic in progress, or start another one.

    For another topic, the explain node then teaches it from the start.
    Topics already completed stay ticked; a waiting question is dropped.
    """
    if topic_index == state["current_topic"] and state["segments"]:
        return resume(state)
    return {
        "current_topic": topic_index,
        "segments": [],
        "question_points": [],
        "segment_index": 0,
        "pending_question": None,
        "attempts": 0,
        "paused_mode": None,
        "paused_speech": [],
    }


# ---------------------------------------------------------------------------
# Repeat (from the outline)
# ---------------------------------------------------------------------------


def can_repeat(state: TeacherState, topic_index: int) -> bool:
    """Only from the outline, for topics already taught or the one in progress."""
    taught = set(state["completed_topics"]) | {state["current_topic"]}
    return state["mode"] == Mode.PAUSED and topic_index in taught and topic_index < len(state["outline"])


def make_repeat_node(llm: LLM):
    """The 'repeat' node: explains state["current_topic"] again, differently, from the start.

    Step 11 sets current_topic to the chosen topic first (keeping the old
    segments if it's the topic in progress, so Regina can avoid repeating them).
    """

    def repeat(state: TeacherState) -> dict:
        segments, points = generate_segments(llm, state, previous=state["segments"])
        return {
            "pending_question": None,
            "attempts": 0,
            "paused_mode": None,
            "paused_speech": [],
            **say_part(segments, points, 0),
        }

    return repeat


def choose_topic_to_repeat(state: TeacherState, topic_index: int) -> dict:
    """Set up repeating a topic: keep its old explanation only if it's the one in progress."""
    if topic_index == state["current_topic"]:
        return {}
    return {"current_topic": topic_index, "segments": [], "question_points": [], "segment_index": 0}


# ---------------------------------------------------------------------------
# Continue (the current speech finished playing)
# ---------------------------------------------------------------------------

CONTINUABLE = {Mode.EXPLAINING, Mode.FEEDBACK, Mode.ANSWERING_STUDENT}


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
    if state["mode"] == Mode.EXPLAINING:
        return "ask_question"
    if state["mode"] == Mode.FEEDBACK and topic_finished(state):
        return "next_topic"
    return "explain"


def after_next_topic(state: TeacherState) -> str:
    """After a topic is done: explain the next one, or finish the lecture."""
    return "closing" if state["current_topic"] is None else "explain"


# ---------------------------------------------------------------------------
# End of the lecture
# ---------------------------------------------------------------------------


def can_end(state: TeacherState) -> bool:
    return state["mode"] != Mode.ENDED


def closing_prompt(state: TeacherState) -> str:
    outline = state["outline"]
    completed = [i for i in state["completed_topics"] if i < len(outline)]
    not_covered = [t["title"] for i, t in enumerate(outline) if i not in completed]
    hard = [outline[i]["title"] for i, s in sorted(state["performance"].items()) if s["incorrect"] > 0]
    good = [outline[i]["title"] for i, s in sorted(state["performance"].items())
            if s["correct"] > 0 and s["incorrect"] == 0]

    lines = ["The lecture is ending now."]
    if completed:
        lines += ["Topics covered, with their main ideas:"]
        lines += [f"- {outline[i]['title']}: {outline[i]['summary']}" for i in completed]
    else:
        lines += ["The student ended before finishing any topic."]
    if not_covered:
        lines += ["Topics not covered yet: " + ", ".join(not_covered)]
    if good:
        lines += ["The student answered questions well on: " + ", ".join(good)]
    if hard:
        lines += ["The student found these harder: " + ", ".join(hard)]

    lines += [
        "",
        "Say goodbye in 3 to 5 spoken sentences:",
        "- briefly recap the main ideas covered,",
        "- mention what they did well, if anything,",
        "- if there were harder topics, encourage them to review those,",
        "- if some topics weren't covered, mention they can continue with those next time.",
    ]
    return "\n".join(lines)


def fallback_closing(state: TeacherState) -> str:
    covered = [state["outline"][i]["title"] for i in state["completed_topics"]]
    text = "That's all for today. "
    if covered:
        text += f"We covered {', '.join(covered)}. "
    hard = [state["outline"][i]["title"] for i, s in state["performance"].items() if s["incorrect"] > 0]
    if hard:
        text += f"It's worth reviewing {', '.join(hard)}. "
    return text + "Great work, see you next time!"


def make_closing_node(llm: LLM):
    """The 'closing' node: a goodbye with a short summary, then the session is over."""

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
