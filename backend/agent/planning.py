"""Step 6: turn the lecture chunks into a topic outline.

The outline doesn't have to follow the slides one by one: the LLM groups
slides into small logical topics (merging or splitting slides as needed) and
records which slides each topic comes from, so later steps teach from the
real slide content.
"""

from pydantic import BaseModel, Field

from agent.contract import LectureChunk
from agent.llm import LLM, LLMError, messages
from agent.state import Mode, OutlineTopic, TeacherState

MAX_TOPICS = 12
# Above this many characters of slide text, slides are condensed first so the
# planning prompt stays well within the model's context window.
MAX_PLANNING_CHARS = 40_000
CONDENSE_BATCH_CHARS = 15_000
FALLBACK_SLIDES_PER_TOPIC = 3


# ---------------------------------------------------------------------------
# What we ask the LLM to return
# ---------------------------------------------------------------------------


class PlannedTopic(BaseModel):
    title: str = Field(description="Short topic title, 2-6 words")
    summary: str = Field(description="1-2 sentences: what the student should understand after this topic")
    key_points: list[str] = Field(description="2-5 key points to teach, taken from the slides")
    source_slides: list[int] = Field(description="Slide numbers this topic is taught from")


class LecturePlan(BaseModel):
    topics: list[PlannedTopic] = Field(min_length=1)


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
    """Roughly one topic per two slides, between 1 and MAX_TOPICS."""
    target = max(1, round(slide_count / 2))
    return max(1, min(target - 1, MAX_TOPICS)), min(target + 2, MAX_TOPICS)


def format_slides(lecture: list[LectureChunk]) -> str:
    return "\n\n".join(f"Slide {chunk.slide}:\n{chunk.text.strip()}" for chunk in lecture)


def planning_prompt(lecture: list[LectureChunk], slide_count: int) -> str:
    low, high = topic_range(slide_count)
    return f"""Here is the content of a lecture, slide by slide:

{format_slides(lecture)}

Split this lecture into between {low} and {high} small topics, in the order they should be taught.

Rules:
- Each topic is ONE concept that can be taught in 2 to 4 minutes.
- Topics don't have to match slides: merge slides about the same idea, or split a slide that covers several ideas.
- Skip slides with no teaching content, such as the title, agenda, "questions?", "thank you" or reference slides.
- For each topic, list the slide numbers it is taught from in source_slides.
- Key points must come from the slides. Do not add information that isn't in them."""


def lecture_title(lecture: list[LectureChunk]) -> str:
    if not lecture:
        return "today's lecture"

    first_slide = lecture[0].text.strip()
    for line in first_slide.splitlines():
        clean = line.strip(" -:\t")
        if 4 <= len(clean) <= 90:
            return clean

    return "today's lecture"


def intro_speech(lecture: list[LectureChunk], outline: list[OutlineTopic]) -> str:
    title = lecture_title(lecture)
    topic_names = [topic["title"] for topic in outline[:3]]

    if topic_names:
        return (
            f"Welcome. Before we start, this lecture is about {title}. "
            f"I planned it into topics like {', '.join(topic_names)}. "
            "Choose a topic from the outline when you are ready, and I will teach it step by step."
        )

    return (
        f"Welcome. Before we start, this lecture is about {title}. "
        "Choose a topic from the outline when you are ready, and I will teach it step by step."
    )


def plan_lecture(llm: LLM, lecture: list[LectureChunk]) -> list[OutlineTopic]:
    """Create the outline. Falls back to a simple slide-based outline if the LLM fails."""
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
            return outline
    except LLMError:
        pass
    return fallback_outline(lecture)


def clean_outline(plan: LecturePlan, lecture: list[LectureChunk]) -> list[OutlineTopic]:
    """Fix the usual LLM slips: made-up slide numbers, empty titles, too many topics."""
    valid_slides = {chunk.slide for chunk in lecture}
    outline = []
    for topic in plan.topics[:MAX_TOPICS]:
        title = topic.title.strip()
        if not title:
            continue
        outline.append(
            OutlineTopic(
                title=title,
                summary=topic.summary.strip(),
                key_points=[point.strip() for point in topic.key_points if point.strip()],
                source_slides=sorted({s for s in topic.source_slides if s in valid_slides}),
            )
        )
    return outline


def fallback_outline(lecture: list[LectureChunk]) -> list[OutlineTopic]:
    """If planning fails, teach the slides in order, a few at a time."""
    outline = []
    for start in range(0, len(lecture), FALLBACK_SLIDES_PER_TOPIC):
        group = lecture[start : start + FALLBACK_SLIDES_PER_TOPIC]
        first_line = next((line.strip() for line in group[0].text.splitlines() if line.strip()), "")
        slides = [chunk.slide for chunk in group]
        outline.append(
            OutlineTopic(
                title=first_line[:60] or f"Slides {slides[0]}-{slides[-1]}",
                summary="",
                key_points=[],
                source_slides=slides,
            )
        )
    return outline


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
        outline = plan_lecture(llm, state["lecture"])
        return {
            "outline": outline,
            "current_topic": None,
            "current_slide": state["lecture"][0].slide if state["lecture"] else None,
            "segments": [],
            "segment_index": 0,
            "question_points": [],
            "completed_topics": [],
            "speech": [intro_speech(state["lecture"], outline)],
            "mode": Mode.INTRO,
        }

    return plan
