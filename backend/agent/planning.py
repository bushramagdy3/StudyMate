"""Step 6: turn the lecture chunks into a topic outline.

The outline doesn't have to follow the slides one by one: the LLM groups
slides into small logical topics (merging or splitting slides as needed) and
records which slides each topic comes from, so later steps teach from the
real slide content.
"""

import math
import re

from pydantic import BaseModel, Field

from agent.contract import LectureChunk, LectureSummarySection
from agent.llm import LLM, LLMError, messages
from agent.personalities import get_personality
from agent.state import Mode, OutlineTopic, TeacherState

MAX_TOPICS = 8
# Above this many characters of slide text, slides are condensed first so the
# planning prompt stays well within the model's context window.
MAX_PLANNING_CHARS = 40_000
CONDENSE_BATCH_CHARS = 15_000


# ---------------------------------------------------------------------------
# What we ask the LLM to return
# ---------------------------------------------------------------------------


class PlannedTopic(BaseModel):
    title: str = Field(description="Short topic title, 2-6 words")
    summary: str = Field(description="1-2 sentences: what the student should understand after this topic")
    key_points: list[str] = Field(description="2-5 key points to teach, taken from the slides")
    source_slides: list[int] = Field(description="Slide numbers this topic is taught from")


class LecturePlan(BaseModel):
    opening: str = Field(
        default="",
        description="One brief, natural spoken sentence introducing what the whole lecture is about",
    )
    topics: list[PlannedTopic] = Field(min_length=1)
    lecture_summary: list[LectureSummarySection] = Field(
        default_factory=list,
        description="A concise, sectioned revision summary of the entire lecture"
    )


class SlideNote(BaseModel):
    slide: int
    notes: str


class CondensedSlides(BaseModel):
    slides: list[SlideNote]


PLANNER_SYSTEM = (
    "You are an expert teacher planning how to teach a lecture. You turn lecture "
    "slides into a clear, ordered list of small topics. You only use content from "
    "the slides and never add facts that aren't there."
)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def topic_range(slide_count: int) -> tuple[int, int]:
    """Broad lesson units: roughly one topic for every four visual pages."""
    target = max(1, math.ceil(slide_count / 4))
    high = min(MAX_TOPICS, max(2, target) if slide_count > 1 else 1)
    return max(1, high - 1), high


def format_slides(lecture: list[LectureChunk]) -> str:
    def label(chunk: LectureChunk) -> str:
        details = []
        if chunk.source_name:
            details.append(chunk.source_name)
        if chunk.source_page:
            details.append(f"page {chunk.source_page}")
        if chunk.start_seconds is not None:
            end = chunk.end_seconds if chunk.end_seconds is not None else chunk.start_seconds
            details.append(f"{chunk.start_seconds:.0f}s-{end:.0f}s")
        suffix = f" ({', '.join(details)})" if details else ""
        return f"Slide {chunk.slide}{suffix}"

    return "\n\n".join(f"{label(chunk)}:\n{chunk.text.strip()}" for chunk in lecture)


def planning_prompt(lecture: list[LectureChunk], slide_count: int) -> str:
    low, high = topic_range(slide_count)
    return f"""Here is the content of a lecture, slide by slide:

{format_slides(lecture)}

Split this lecture into between {low} and {high} small topics, in the order they should be taught.

Rules:
- Each topic is ONE concept that can be taught in 2 to 4 minutes.
- Topics don't have to match slides: merge slides about the same idea, or split a slide that covers several ideas.
- Treat all uploaded files as one continuous lecture. A file boundary alone is never a topic boundary.
- Skip slides with no teaching content, such as the title, agenda, "questions?", "thank you" or reference slides.
- For each topic, list the slide numbers it is taught from in source_slides.
- Key points must come from the slides. Do not add information that isn't in them.
- A topic title is a 2-6 word concept label for the outline, not a sentence or a visual description.
  Never use wording such as "This slide", "This page", "part of a", or "the slide shows".
  Use readable title case while preserving acronyms such as HTTP, DNS, and TCP.
- Also provide opening: ONE natural, student-facing spoken sentence that briefly says
  what the whole lecture is about. Describe the material directly, not the lesson plan.
  Do not greet, repeat the lecture title, mention slides, use learning-objective wording,
  or give instructions; the app speaks the welcome and the outline instruction separately.
- Also write lecture_summary as 2 to 4 short revision sections. Each section needs a
  2-5 word heading and 1 to 3 concise bullet points. Cover the key concepts in order.
  It is read silently in the student's revision popup, so make it easy to scan."""


def intro_speech(
    outline: list[OutlineTopic],
    environment,
    opening: str = "",
) -> str:
    role = get_personality(environment).role
    tag = {
        "professor": "[reassuring]",
        "tutor": "[reassuring]",
        "study friend": "[excited]",
    }[role]

    brief = " ".join(opening.split()).strip() or fallback_opening(outline)[1]
    return (
        f"{tag} Welcome. {brief.rstrip('.')}. "
        "Choose a topic from the outline when you are ready, and I will teach it step by step."
    )


def fallback_opening(outline: list[OutlineTopic]) -> tuple[str, str]:
    """Create a clean opening when the planner cannot provide one."""
    topic_names = [topic["title"].strip() for topic in outline[:3] if topic["title"].strip()]
    if not topic_names:
        return "Lecture overview", "A guided introduction to the material in these slides"

    title = topic_names[0]
    if len(topic_names) == 1:
        overview = f"We will focus on {title}"
    else:
        overview = f"We will connect {', '.join(topic_names)}"
    return title, overview


def fallback_lecture_summary(outline: list[OutlineTopic]) -> list[dict]:
    """Keep the revision popup useful if the planner cannot make an LLM summary."""
    sections = [
        LectureSummarySection(
            heading=topic["title"],
            points=[topic["summary"] or ", ".join(topic["key_points"]) or topic["title"]],
        )
        for topic in outline
    ]
    return [section.model_dump() for section in sections[:4]] or [
        {"heading": "Lecture overview", "points": ["No revision summary is available yet."]}
    ]


def plan_lecture_with_summary(
    llm: LLM,
    lecture: list[LectureChunk],
) -> tuple[list[OutlineTopic], list[dict], str]:
    """Create the outline and a revision-ready summary in one planning request."""
    try:
        planning_input = lecture
        if sum(len(chunk.text) for chunk in lecture) > MAX_PLANNING_CHARS:
            planning_input = condense_slides(llm, lecture)

        plan = llm.chat_json(
            messages(PLANNER_SYSTEM, planning_prompt(planning_input, len(lecture))),
            LecturePlan,
        )
        outline = clean_outline(plan, lecture)
        if outline:
            summary = [section.model_dump() for section in plan.lecture_summary]
            return (
                outline,
                summary or fallback_lecture_summary(outline),
                plan.opening,
            )
    except LLMError:
        pass
    outline = fallback_outline(lecture)
    return outline, fallback_lecture_summary(outline), ""


def plan_lecture(llm: LLM, lecture: list[LectureChunk]) -> list[OutlineTopic]:
    """Create the outline. Kept as a small compatibility wrapper for callers/tests."""
    outline, _summary, _opening = plan_lecture_with_summary(llm, lecture)
    return outline


def clean_outline(plan: LecturePlan, lecture: list[LectureChunk]) -> list[OutlineTopic]:
    """Publish only broad, source-backed topics with readable labels."""
    valid_slides = {chunk.slide for chunk in lecture}
    outline = []
    for position, topic in enumerate(plan.topics):
        source_slides = sorted({slide for slide in topic.source_slides if slide in valid_slides})
        if not source_slides:
            continue
        cleaned = OutlineTopic(
            title=topic_title(topic.title, topic.key_points, source_slides, lecture, position + 1),
            summary=topic.summary.strip(),
            key_points=[point.strip() for point in topic.key_points if point.strip()],
            source_slides=source_slides,
        )
        if outline and outline[-1]["title"].casefold() == cleaned["title"].casefold():
            outline[-1] = merge_topic_group([outline[-1], cleaned])
        else:
            outline.append(cleaned)
    return coalesce_topics(outline, topic_range(len(lecture))[1])


def fallback_outline(lecture: list[LectureChunk]) -> list[OutlineTopic]:
    """If planning fails, create a small number of source-backed lesson units."""
    outline = []
    max_topics = topic_range(len(lecture))[1]
    slides_per_topic = max(1, math.ceil(len(lecture) / max_topics))
    for start in range(0, len(lecture), slides_per_topic):
        group = lecture[start : start + slides_per_topic]
        slides = [chunk.slide for chunk in group]
        outline.append(
            OutlineTopic(
                title=topic_title("", [], slides, lecture, len(outline) + 1),
                summary="",
                key_points=[],
                source_slides=slides,
            )
        )
    return coalesce_topics(outline, max_topics)


_TITLE_PREFIX = re.compile(r"^(?:this|the)\s+(?:slide|page)(?:\s+shows|\s+is|\s*,)?\s*", re.I)
_TITLE_WORDS = {"is", "are", "was", "were", "sends", "send", "shows", "show", "uses", "use", "used", "explains", "explain", "covers", "cover", "introduces", "introduce", "can", "will"}
_ACRONYM = re.compile(r"^[A-Z]{2,}(?:[/.-][A-Z0-9.]+)*$")


def topic_title(
    proposed: str,
    key_points: list[str],
    source_slides: list[int],
    lecture: list[LectureChunk],
    position: int,
) -> str:
    """Turn planner/extractor prose into a short outline label."""
    source_text = [
        line.strip()
        for chunk in lecture
        if chunk.slide in set(source_slides)
        for line in chunk.text.splitlines()
        if line.strip()
    ]
    # A model title is useful only when it is actually a compact label. Raw
    # descriptions such as "This slide, part of ..." must not win over the
    # source's own heading.
    candidates = []
    if _is_compact_label(proposed):
        candidates.append(proposed)
    candidates.extend([*source_text, *key_points])
    for candidate in candidates:
        label = _label_from_text(candidate)
        if label:
            return label
    return f"Topic {position}"


def _is_compact_label(value: str) -> bool:
    words = value.strip().split()
    # Keep a concise one-word concept when the model has supplied one, even
    # though the prompt prefers 2-6 words (for example, "Pipelining").
    if not 1 <= len(words) <= 6:
        return False
    lowered = value.casefold()
    return not lowered.startswith(("this slide", "this page", "the slide", "the page", "part of"))


def _label_from_text(value: str) -> str:
    text = " ".join(value.replace("…", " ").split()).strip(" -:;,.!")
    if not text:
        return ""
    lowered = text.casefold()
    if lowered.startswith(("this slide", "this page", "the slide", "the page")):
        match = re.search(r"part of\s+(?:a|an|the)?\s*([^.,;]+)", text, re.I)
        if match:
            text = re.split(r"\b(?:lecture|course|presentation|deck)\b", match.group(1), flags=re.I)[0].strip()
        else:
            text = _TITLE_PREFIX.sub("", text)
    text = re.split(r"[:;]", text, maxsplit=1)[0].strip()
    words = text.split()
    if not words:
        return ""
    for index, word in enumerate(words):
        if word.strip(".,!?;").casefold() in _TITLE_WORDS and index >= 2:
            words = words[:index]
            break
    if len(words) > 6:
        words = words[:6]
    label = " ".join(words).strip(" -:;,.!")
    if not label or label.casefold().startswith(("this slide", "this page", "part of")):
        return ""
    return _title_case(label)


def _title_case(value: str) -> str:
    words = []
    for word in value.split():
        bare = word.strip(".,:;()")
        if _ACRONYM.fullmatch(bare):
            words.append(word)
        elif bare.isupper():
            words.append(word.capitalize())
        else:
            words.append(word)
    return " ".join(words)


def merge_topic_group(topics: list[OutlineTopic]) -> OutlineTopic:
    """Join adjacent outline units without dropping their source references."""
    first = topics[0]
    titles = [topic["title"] for topic in topics]
    title = " and ".join(titles[:2]) if len(set(titles)) > 1 else first["title"]
    return OutlineTopic(
        title=_label_from_text(title) or first["title"],
        summary=" ".join(topic["summary"] for topic in topics if topic["summary"]).strip(),
        key_points=list(dict.fromkeys(point for topic in topics for point in topic["key_points"]))[:5],
        source_slides=sorted({slide for topic in topics for slide in topic["source_slides"]}),
    )


def coalesce_topics(topics: list[OutlineTopic], maximum: int) -> list[OutlineTopic]:
    """Keep an outline at its lesson-unit scale even if the planner over-splits."""
    if len(topics) <= maximum:
        return topics
    size = math.ceil(len(topics) / maximum)
    return [merge_topic_group(topics[start : start + size]) for start in range(0, len(topics), size)]


# ---------------------------------------------------------------------------
# Long lectures
# ---------------------------------------------------------------------------


def condense_slides(llm: LLM, lecture: list[LectureChunk]) -> list[LectureChunk]:
    """Shorten each slide to its key teaching notes, a batch of slides at a time.

    Only used for planning; the full slide text is kept in the state for teaching.
    """
    condensed = []
    for batch in _batches(lecture, CONDENSE_BATCH_CHARS):
        prompt = (
            f"{format_slides(batch)}\n\n"
            "For each slide above, write short notes (at most 3 sentences) that keep "
            "its main ideas, key terms, definitions and numbers. Keep every slide number."
        )
        try:
            notes = llm.chat_json(messages(PLANNER_SYSTEM, prompt), CondensedSlides)
            by_slide = {note.slide: note.notes for note in notes.slides}
        except LLMError:
            by_slide = {}
        for chunk in batch:
            text = by_slide.get(chunk.slide) or chunk.text[:500]  # cut the slide if notes are missing
            condensed.append(LectureChunk(slide=chunk.slide, text=text))
    return condensed


def _batches(lecture: list[LectureChunk], max_chars: int) -> list[list[LectureChunk]]:
    batches, current, size = [], [], 0
    for chunk in lecture:
        if current and size + len(chunk.text) > max_chars:
            batches.append(current)
            current, size = [], 0
        current.append(chunk)
        size += len(chunk.text)
    if current:
        batches.append(current)
    return batches


# ---------------------------------------------------------------------------
# Helpers for later steps
# ---------------------------------------------------------------------------


def slides_text(lecture: list[LectureChunk], slide_numbers: list[int]) -> str:
    """The full text of the given slides, to teach a topic from (used in Step 7)."""
    wanted = set(slide_numbers)
    return format_slides([chunk for chunk in lecture if chunk.slide in wanted])


# ---------------------------------------------------------------------------
# The LangGraph node
# ---------------------------------------------------------------------------


def make_plan_node(llm: LLM):
    """The 'plan' node: runs once at the start of a session."""

    def plan(state: TeacherState) -> dict:
        outline, lecture_summary, opening = plan_lecture_with_summary(llm, state["lecture"])
        intro = intro_speech(outline, state["environment"], opening)
        return {
            "outline": outline,
            "lecture_summary": lecture_summary,
            "current_topic": None,
            "current_slide": state["lecture"][0].slide if state["lecture"] else None,
            "segments": [],
            "segment_index": 0,
            "question_points": [],
            "completed_topics": [],
            "speech": [intro],
            "history": [{"role": "teacher", "text": intro}],
            "mode": Mode.INTRO,
        }

    return plan
