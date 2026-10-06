"""The "Summary" item at the top of the outline (private tutor only).

Clicking it makes Regina summarise the whole lecture PDF. The summary is
written once and reused if it's clicked again. When it has finished playing,
"continue" takes the student back to exactly where they were in the lecture.
"""

from pydantic import BaseModel

from agent.contract import LectureChunk
from agent.explaining import enter_topic, save_progress
from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.planning import MAX_PLANNING_CHARS, condense_slides, format_slides
from agent.questioning import topic_finished
from agent.state import Mode, TeacherState

SUMMARY_SEGMENTS = "3 to 5"


class Summary(BaseModel):
    segments: list[str]


def can_summarize(state: TeacherState) -> bool:
    return get_personality(state["environment"]).offers_summary and state["mode"] != Mode.ENDED


def summary_prompt(lecture: list[LectureChunk], topic_titles: list[str]) -> str:
    return "\n".join(
        [
            "Here is the whole lecture, slide by slide:",
            "",
            format_slides(lecture),
            "",
            "The lecture's topics, in order: " + ", ".join(topic_titles),
            "",
            "The student asked for a summary of the entire lecture.",
            f"Summarise it in {SUMMARY_SEGMENTS} short spoken segments, following the order of the topics.",
            "Each segment is 2 to 4 sentences and covers the main ideas, key terms and conclusions.",
            "Only use content from the lecture. Don't ask the student questions.",
        ]
    )


def write_summary(llm: LLM, state: TeacherState) -> list[str]:
    lecture = state["lecture"]
    personality = get_personality(state["environment"])
    try:
        if sum(len(chunk.text) for chunk in lecture) > MAX_PLANNING_CHARS:
            lecture = condense_slides(llm, lecture)
        titles = [topic["title"] for topic in state["outline"]]
        summary = llm.chat_json(
            messages(build_system_prompt(personality), summary_prompt(lecture, titles)), Summary
        )
        segments = [segment.strip() for segment in summary.segments if segment.strip()]
        if segments:
            return segments
    except LLMError:
        pass
    return fallback_summary(state)


def fallback_summary(state: TeacherState) -> list[str]:
    """A plain summary from the outline, if the LLM can't be reached."""
    lines = [f"{t['title']}: {t['summary']}" if t["summary"] else t["title"] for t in state["outline"]]
    return ["Here's a quick summary of the lecture. " + " ".join(lines)]


def make_summary_node(llm: LLM):
    """The 'summary' node: says the lecture summary, remembering where the student was."""

    def summary(state: TeacherState) -> dict:
        segments = state["summary"] or write_summary(llm, state)
        update = {
            "summary": segments,
            "speech": segments,
            "mode": Mode.SUMMARIZING,
            "pending_question": None,
            "attempts": 0,
            "history": [{"role": "teacher", "text": " ".join(segments)}],
        }
        if state["mode"] != Mode.SUMMARIZING:
            update["topic_progress"] = save_progress(state)  # where to come back to
        return update

    return summary


def back_to_lecture(state: TeacherState) -> dict:
    """The 'back_to_lecture' node: after the summary, resume exactly where they were."""
    saved = state["topic_progress"].get(state["current_topic"])
    if saved and saved["segment_index"] >= len(saved["segments"]):
        # They'd finished the topic's last question: move on rather than replay it.
        return {key: saved[key] for key in ("segments", "question_points", "segment_index")}
    return enter_topic(state, state["current_topic"], state["topic_progress"], restart_current=False)


def after_back_to_lecture(state: TeacherState) -> str:
    """Next topic if the current one was finished; otherwise the lecture is set up again."""
    if topic_finished(state):
        return "next_topic"
    return "explain" if not state["segments"] else "wait"
