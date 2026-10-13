"""Step 7: Regina explains the current topic, in sentence-sized spoken segments.

A topic's explanation is written once, as `segments_per_topic` segments, and
delivered in parts: each part ends where the teacher asks a question. The LLM
chooses where the questions go (after a complete idea), e.g. for 4 segments
and 2 questions it might choose question_points = [1, 4]:

    [0] -> question -> [1, 2, 3] -> question

Pacing: the LLM judges each topic and picks a pace. A deep concept, or one
that brings in terms the student hasn't met, is "slow": more segments, every
new term defined, smaller steps, an example and a recap, spoken a little
slower. An intuitive topic, or one built on ideas already covered, is
"quick": fewer segments, no re-defining, spoken a little faster.

While a part is playing, state["segment_index"] is the index of its FIRST
segment. The frontend reports positions inside the part it received, so:
- raise_hand(segment_index=i)  -> resume from state["segment_index"] + i
- continue                     -> move on to next_stop(...)
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.planning import slides_text
from agent.state import Mode, OutlineTopic, TeacherState

RECENT_HISTORY = 6  # how many recent lines of conversation to show the LLM


Pace = Literal["slow", "normal", "quick"]


class Explanation(BaseModel):
    pace: Pace = Field(
        default="normal",
        description='"slow" for deep or new concepts, "quick" for intuitive or familiar ones',
    )
    segments: list[str]
    segment_slides: list[int] = Field(
        description=(
            "One source slide number for each explanation segment, using the provided "
            "global slide numbers. Repeat a number while continuing to explain the same page."
        ),
    )
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
# Pacing
# ---------------------------------------------------------------------------


def segment_range(segments_per_topic: int) -> tuple[int, int]:
    """How many segments a topic may have: fewer for quick topics, more for slow ones.

    The personality's segments_per_topic is the normal amount, e.g. 4 -> 3 to 8.
    """
    return max(2, segments_per_topic - 1), segments_per_topic * 2


def known_ideas(state: TeacherState, index: int) -> list[str]:
    """What the student has already been taught: other finished topics and their key points."""
    lines = []
    for i in state["completed_topics"]:
        if i == index:
            continue
        topic = state["outline"][i]
        points = "; ".join(topic["key_points"][:4])
        lines.append(f"- {topic['title']}" + (f": {points}" if points else ""))
    return lines


# ---------------------------------------------------------------------------
# Writing the explanation
# ---------------------------------------------------------------------------


def explain_prompt(state: TeacherState, previous: list[str] | None = None) -> str:
    personality = get_personality(state["environment"])
    index = state["current_topic"]
    topic = state["outline"][index]
    count = personality.segments_per_topic
    fewest, most = segment_range(count)
    questions = personality.questions_per_topic
    known = known_ideas(state, index)

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

    lines.append(
        "The session introduction has already happened. Start teaching this topic directly. "
        "Do not greet the student or introduce yourself again."
    )
    if known:
        lines += [
            "Already taught (the student knows these terms; don't re-teach or re-define "
            "them, but you can connect to them in a sentence):",
            *known,
        ]

    if previous is not None:
        lines += ["", "The student asked to hear this topic explained again."]
        if previous:
            lines += ["Your previous explanation was:", *(f'"{segment}"' for segment in previous)]
        lines += [
            "Explain it again differently: use simpler words, a new example or analogy, "
            "and smaller steps. Don't repeat the same sentences. They found it hard, so "
            "don't choose the \"quick\" pace.",
        ]

    recent = state["history"][-RECENT_HISTORY:]
    if recent:
        lines += ["", "Recent conversation, for context:"]
        lines += [f"{line['role'].capitalize()}: {line['text']}" for line in recent]

    lines += [
        "",
        "First judge how this topic should be paced, and set pace:",
        f'- "slow": a deep or abstract concept, or it introduces terms or ideas the student '
        f"hasn't met before. Use {count + 1} to {most} segments. Define each new term in plain "
        "words the first time you use it, build the idea in small steps, give a concrete "
        "example, and end with a one-sentence recap.",
        f'- "normal": a typical topic. Use about {count} segments.',
        f'- "quick": intuitive, or it mostly builds on ideas already taught. Use {fewest} to '
        f"{count} segments. Skip what the student already knows and focus on what's new.",
        "A topic mixing a familiar idea with one new term is \"normal\": go slowly only on the new term.",
        "Be conservative: an opening or foundation topic that establishes vocabulary is slow unless it is genuinely trivial. "
        "Never choose quick merely because a slide is short.",
        "",
        f"Write the explanation as {fewest} to {most} segments (matching the pace), in teaching order.",
        "Each segment is 2 to 4 short spoken sentences about one small idea.",
        "Use complete, concise sentences; each sentence becomes its own playback and resume chunk.",
        "Teach clearly: define new terms before using them, then explain the idea step by step.",
        "When a slide contains a diagram, table, equation, chart, or visual example, explicitly explain what it shows and how it supports the concept.",
        "If the slide has labels, axes, arrows, rows, columns, formulas, or examples, refer to their meaning rather than vaguely saying 'the visual'.",
        "segment_slides is required. For every segment, return its source slide in segment_slides. The list must have the same length as segments and use only the listed topic slide numbers.",
        "Choose the page that supplies the exact fact or visual being explained. If a later PDF, PowerPoint, diagram, or textbook page supplies an idea, the segment that teaches it must use that page instead of the opening page.",
        "Keep the same source slide for consecutive segments whenever they explain the same visual or idea. Switch only when the next segment genuinely depends on another page, such as a specific diagram, example, or textbook page.",
        "Start directly with the explanation. Do not recap a previous segment or announce a page change. When a switch genuinely helps the listener, weave one brief, varied reference to the new visual into that segment; never repeat a transition phrase.",
        "Don't ask the student questions; questions come separately.",
        "",
        f"Also choose where to pause and ask the student a question: in question_after, list "
        f"exactly {questions} segment number(s), each right after a complete idea has been "
        "explained. The last one must be the number of your final segment (the end of the topic).",
        "Don't mention segments, slide numbers or these instructions.",
    ]
    return "\n".join(lines)


def generate_segments(
    llm: LLM, state: TeacherState, previous: list[str] | None = None
) -> tuple[list[str], list[int]]:
    """The current topic's explanation as (segments, question_points)."""
    segments, points, _pace, _slides = generate_explanation(llm, state, previous)
    return segments, points


def generate_explanation(
    llm: LLM, state: TeacherState, previous: list[str] | None = None
) -> tuple[list[str], list[int], str, list[int]]:
    """The current topic's explanation as (segments, question_points, pace, slides).

    `previous` is set when the student asked to hear the topic again (repeat):
    the old explanation, or [] if it's no longer available.
    """
    personality = get_personality(state["environment"])
    topic = state["outline"][state["current_topic"]]
    _fewest, most = segment_range(personality.segments_per_topic)
    try:
        explanation = llm.chat_json(
            messages(build_system_prompt(personality), explain_prompt(state, previous)),
            Explanation,
            temperature=0.7,
            request_timeout=30,
            max_attempts=1,
        )
        pace = explanation.pace
        if previous is not None and pace == "quick":
            pace = "normal"  # they asked to hear it again: never rush it
        grouped_segments, grouped_slides = fit_segment_sources(
            explanation.segments,
            explanation.segment_slides,
            most,
            topic["source_slides"],
        )
        segments, group_ends = split_into_sentence_segments(grouped_segments)
        if segments:
            mapped_points = [
                group_ends[point - 1]
                for point in explanation.question_after
                if 1 <= point <= len(group_ends)
            ]
            points = choose_question_points(
                mapped_points, len(segments), personality.questions_per_topic
            )
            return segments, points, pace, expand_group_slides(grouped_slides, group_ends)
    except LLMError:
        pass
    grouped_segments = fallback_segments(topic)
    segments, group_ends = split_into_sentence_segments(grouped_segments)
    grouped_points = default_question_points(
        len(grouped_segments), personality.questions_per_topic
    )
    points = [group_ends[point - 1] for point in grouped_points]
    return segments, points, "normal", fallback_segment_slides(segments, topic["source_slides"])


def fit_segment_sources(
    segments: list[str], proposed_slides: list[int], maximum: int, source_slides: list[int]
) -> tuple[list[str], list[int]]:
    """Keep each explanation group paired with the source page it actually uses."""
    # A partial model response must never invent a page change. Staying on the
    # opening page is less surprising than treating a short, invalid list as a
    # real source map.
    mapped_slides = (
        proposed_slides if len(proposed_slides) == len(segments) else [None] * len(segments)
    )
    pairs = [
        (segment.strip(), mapped_slides[index])
        for index, segment in enumerate(segments)
        if segment.strip()
    ]
    valid_slides = set(source_slides)
    fallback = source_slides[0] if source_slides else None
    pairs = [(segment, slide if slide in valid_slides else fallback) for segment, slide in pairs]
    # Some model responses repeat the same sentence when they change pace.
    # Remove only exact consecutive duplicates; distinct explanations remain.
    deduplicated = []
    for segment, slide in pairs:
        normalized = " ".join(segment.casefold().split())
        if not deduplicated or normalized != deduplicated[-1][0]:
            deduplicated.append((normalized, segment, slide))
    pairs = [(segment, slide) for _normalized, segment, slide in deduplicated]
    # Preserve a segment's source truth. Only collapse adjacent ideas when
    # they already refer to the same page; never merge text from two pages.
    while len(pairs) > maximum:
        merge_at = next(
            (index for index in range(len(pairs) - 1) if pairs[index][1] == pairs[index + 1][1]),
            None,
        )
        if merge_at is None:
            break
        first, second = pairs[merge_at : merge_at + 2]
        pairs[merge_at : merge_at + 2] = [(f"{first[0]} {second[0]}", first[1])]
    return (
        [segment for segment, _slide in pairs],
        [slide for _segment, slide in pairs],
    )


def expand_group_slides(group_slides: list[int | None], group_ends: list[int]) -> list[int]:
    """Repeat a group's source page for every sentence-sized playback chunk."""
    expanded = []
    start = 0
    for slide, end in zip(group_slides, group_ends):
        if slide is not None:
            expanded.extend([slide] * (end - start))
        start = end
    return expanded


def fallback_segment_slides(segments: list[str], source_slides: list[int]) -> list[int]:
    """A safe fallback stays on the opening source page rather than guessing changes."""
    return [source_slides[0]] * len(segments) if source_slides else []


def add_slide_transitions(
    segments: list[str],
    points: list[int],
    segment_slides: list[int],
) -> tuple[list[str], list[int], list[int]]:
    """Keep source changes silent; the model already owns natural visual references."""
    if len(segment_slides) != len(segments):
        return segments, points, []
    return list(segments), points, list(segment_slides)


def fit_segments(segments: list[str], count: int) -> list[str]:
    """Drop empty segments; if there are too many, merge the extras into the last one."""
    segments = [segment.strip() for segment in segments if segment.strip()]
    if len(segments) > count:
        segments = segments[: count - 1] + [" ".join(segments[count - 1 :])]
    return segments


def split_into_sentence_segments(segments: list[str]) -> tuple[list[str], list[int]]:
    """Flatten explanation groups into sentence-sized playback chunks.

    The returned group-end positions let question points from the LLM stay at
    the end of the same idea after a multi-sentence group is split.
    """
    sentences = []
    group_ends = []

    for segment in segments:
        parts = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", segment.strip())
            if part.strip()
        ]
        sentences.extend(parts or [segment.strip()])
        group_ends.append(len(sentences))

    return sentences, group_ends


def fallback_segments(topic: OutlineTopic) -> list[str]:
    """A plain explanation from the outline, if the LLM can't be reached."""
    segments = [topic["summary"].strip()] if topic["summary"].strip() else []
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
            segments, points, pace, segment_slides = generate_explanation(llm, state)
            segments, points, segment_slides = add_slide_transitions(
                segments,
                points,
                segment_slides,
            )
            return say_part(
                segments,
                points,
                0,
                segment_slides,
            ) | {"pace": pace}
        return say_part(
            state["segments"],
            state["question_points"],
            state["segment_index"],
            state["segment_slides"],
        )

    return explain


def slide_for_segment(segments: list[str], segment_index: int, slide_numbers: list[int] | None) -> int | None:
    if not slide_numbers:
        return None
    if not segments:
        return slide_numbers[0]

    safe_index = max(0, min(segment_index, len(segments) - 1))
    slide_index = min(
        int(safe_index * len(slide_numbers) / len(segments)),
        len(slide_numbers) - 1,
    )
    return slide_numbers[slide_index]


def say_part(
    segments: list[str],
    points: list[int],
    segment_index: int,
    segment_slides: list[int] | None = None,
) -> dict:
    """State update that says the part of the explanation starting at segment_index."""
    segment_index = min(segment_index, len(segments) - 1)
    stop = next_stop(segment_index, points, len(segments))
    speech = segments[segment_index:stop]
    segment_slides = segment_slides or []
    current_slide = (
        segment_slides[segment_index]
        if len(segment_slides) == len(segments)
        else slide_for_segment(segments, segment_index, segment_slides)
    )
    return {
        "segments": segments,
        "segment_slides": segment_slides,
        "question_points": points,
        "segment_index": segment_index,
        "current_slide": current_slide,
        "speech": speech,
        "speech_slides": segment_slides[segment_index:stop],
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
            "segment_slides": state["segment_slides"],
            "question_points": state["question_points"],
            "segment_index": resume_index(state),
            "pace": state.get("pace", "normal"),
        }
    return progress


def enter_topic(state: TeacherState, topic: int, progress: dict, restart_current: bool = True) -> dict:
    """State update that makes `topic` the current one.

    - never started: segments are cleared, so the explain node writes them;
    - left halfway: resumes where the student left it;
    - finished (or it's the topic they're in): from the start, same explanation.
      With restart_current=False the topic they're in resumes instead (after the summary).
    """
    update = {
        "current_topic": topic,
        "topic_progress": progress,
        "pending_question": None,
        "attempts": 0,
        "topic_exit_pending": False,
    }
    saved = progress.get(topic)
    if saved is None:
        return update | {"segments": [], "question_points": [], "segment_index": 0, "pace": "normal"}

    start = saved["segment_index"]
    finished = topic in state["completed_topics"] or start >= len(saved["segments"])
    if finished or (restart_current and topic == state["current_topic"]):
        start = 0
    return update | say_part(
        saved["segments"],
        saved["question_points"],
        start,
        saved.get("segment_slides", []),
    ) | {"pace": saved.get("pace", "normal")}
