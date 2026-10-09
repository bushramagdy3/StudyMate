"""The mini quiz at the end of the lecture.

It unlocks in the outline once every topic is completed. The LLM writes the
whole quiz in one call, and decides the kind of each question to suit the
subject: multiple choice ("mcq") for recognising facts and concepts, typed
answers ("text") for producing something (code, a translation, a calculation,
an explanation). e.g. biology: mostly mcq; German: a mix; programming: mostly
text. It says why in `style_note`, which the student sees.

Which topics the questions are about (decided here, in code, not by the LLM):
- topics the student got wrong get 2 questions each, every other topic gets 1
  (so their understanding of everything is still checked);
- no mistakes: the questions are spread evenly over all topics.
"Wrong" means: during the lecture for the first quiz (topics_to_improve, even if
they got it right on the retry), and in the last quiz for a new quiz.

Like the topics, the quiz can be:
- restarted: the same questions again;
- reprompted ("new"): new questions, focused on what they got wrong last time.

Marking: multiple choice is marked by code (instant). Typed answers are graded
by the LLM, all in one call; if that fails, by matching key words.
"""

import random
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from agent.contract import Quiz, QuizQuestion, QuizResult, QuizReview, Topic
from agent.llm import LLM, LLMError, messages
from agent.planning import slides_text
from agent.state import OutlineTopic, TeacherState

MIN_QUESTIONS = 5
MAX_QUESTIONS = 10
OPTION_COUNT = 4
MAX_ANSWER_CHARS = 2000  # a typed answer longer than this is cut before grading

# ---------------------------------------------------------------------------
# Which topic each question is about
# ---------------------------------------------------------------------------


def plan_quiz_topics(topic_count: int, weak_topics: list[int]) -> list[int]:
    """The topic of each question, in lecture order.

    e.g. 4 topics, weak [2]    -> [0, 1, 2, 2, 3]   (2 questions on topic 2, 1 on the rest)
         3 topics, no mistakes -> [0, 0, 1, 1, 2]   (balanced)
    """
    weak = sorted({i for i in weak_topics if 0 <= i < topic_count})
    others = [i for i in range(topic_count) if i not in weak]

    if not weak:
        # Balanced: go round all topics until there are enough questions.
        total = min(max(MIN_QUESTIONS, topic_count), MAX_QUESTIONS)
        return sorted(i % topic_count for i in range(total))

    # One question on every topic (weak ones first if they don't all fit),
    # then a second one on each weak topic while there's room.
    plan = (weak + others)[:MAX_QUESTIONS]
    plan += weak[: MAX_QUESTIONS - len(plan)]
    # A short lecture: top up, weak topics first.
    filler = weak + others
    while len(plan) < MIN_QUESTIONS:
        plan.append(filler[len(plan) % len(filler)])
    return sorted(plan)


# ---------------------------------------------------------------------------
# Writing the questions (LLM)
# ---------------------------------------------------------------------------


class DraftQuestion(BaseModel):
    topic_index: int = Field(description="Index of the topic this question tests")
    kind: Literal["mcq", "text"] = Field(
        default="mcq", description='"mcq": pick one of 4 options; "text": the student types the answer'
    )
    question: str = Field(description="The question, one or two sentences")
    options: list[str] = Field(default_factory=list, description='"mcq" only: exactly 4 options, one correct')
    correct_index: int = Field(default=0, description='"mcq" only: index (0-3) of the correct option')
    expected_answer: str = Field(default="", description='"text" only: a short model answer')
    code_answer: bool = Field(default=False, description='"text" only: true if the answer is code')
    explanation: str = Field(description="1-2 sentences: why the answer is right")


class DraftQuiz(BaseModel):
    style_note: str = Field(
        default="", description="One sentence for the student: why this mix of question kinds suits the lecture"
    )
    questions: list[DraftQuestion] = Field(min_length=1)


QUIZ_SYSTEM_PROMPT = (
    "You write short quizzes that check a student understood a lecture. Questions test "
    "understanding (why, what happens if, which is an example, apply it), not trivia like "
    "slide numbers. Write plain text: no markdown, no [bracketed] voice tags."
)

STYLE_GUIDE = """Choose the kind of each question to suit the subject and the topic:
- "mcq" (4 options) when the skill is recognising or telling apart facts, terms and
  concepts, e.g. biology, history, theory. Wrong options are plausible but clearly
  wrong to someone who understood.
- "text" (typed answer) when the skill is producing something: writing or fixing code,
  translating, conjugating or forming sentences in a language, calculating, or
  explaining a process in their own words. Ask for a short answer (a word, a line of
  code, a sentence or two), and give a model answer.
So a biology lecture is mostly mcq, a language lecture a balance of both, and a
programming lecture mostly text. Decide from the lecture, not from these examples."""


def quiz_prompt(state: TeacherState, plan: list[int], avoid: list[str]) -> str:
    outline = state["outline"]
    lines = ["Write a quiz about this lecture.", "", "Topics:"]
    for index in sorted(set(plan)):
        topic = outline[index]
        lines += [
            f"Topic {index}: {topic['title']}",
            f"  Summary: {topic['summary']}",
            "  Key points: " + "; ".join(topic["key_points"]),
            "  Slides: " + (slides_text(state["lecture"], topic["source_slides"]) or "(none)"),
        ]
    counts = {i: plan.count(i) for i in sorted(set(plan))}
    lines += [
        "",
        f"Write exactly {len(plan)} questions: "
        + ", ".join(f"{n} on topic {i}" for i, n in counts.items())
        + ".",
        "Questions on the same topic must test different ideas.",
        "",
        STYLE_GUIDE,
    ]
    if avoid:
        lines += ["", "Don't repeat these questions from earlier quizzes:"]
        lines += [f"- {question}" for question in avoid]
    lines += [
        "",
        'Reply with JSON only: {"style_note": "...", "questions": ['
        '{"topic_index": 0, "kind": "mcq", "question": "...", "options": ["...", "...", "...", "..."], '
        '"correct_index": 0, "explanation": "..."}, '
        '{"topic_index": 1, "kind": "text", "question": "...", "expected_answer": "...", '
        '"code_answer": false, "explanation": "..."}]}',
    ]
    return "\n".join(lines)


@dataclass
class QuizItem:
    """One question with its answer (the answer stays on the server)."""

    topic_index: int
    question: str
    explanation: str
    kind: str = "mcq"
    options: list[str] = field(default_factory=list)  # mcq
    correct_index: int = 0  # mcq
    expected_answer: str = ""  # text
    code_answer: bool = False  # text


VOICE_TAG = re.compile(r"\[[a-z ]+\]\s*", re.IGNORECASE)


def clean_text(text: str) -> str:
    return VOICE_TAG.sub("", text).strip()


def clean_draft(draft: DraftQuestion, topic_count: int) -> QuizItem | None:
    """A usable question, or None if it's broken (wrong option count, no model answer...)."""
    question = clean_text(draft.question)
    if not 0 <= draft.topic_index < topic_count or not question:
        return None
    explanation = clean_text(draft.explanation)

    if draft.kind == "text":
        # Code keeps its exact text; [brackets] can be real syntax there.
        expected = draft.expected_answer.strip() if draft.code_answer else clean_text(draft.expected_answer)
        if not expected:
            return None
        return QuizItem(
            draft.topic_index, question, explanation, kind="text",
            expected_answer=expected, code_answer=draft.code_answer,
        )

    options = [clean_text(option) for option in draft.options]
    if (
        len(options) != OPTION_COUNT
        or not all(options)
        or len({o.lower() for o in options}) != OPTION_COUNT
        or not 0 <= draft.correct_index < OPTION_COUNT
    ):
        return None
    return QuizItem(draft.topic_index, question, explanation, options=options, correct_index=draft.correct_index)


def shuffle_options(item: QuizItem, rng: random.Random) -> QuizItem:
    """LLMs often put the right answer first, so mix the options up."""
    if item.kind != "mcq":
        return item
    order = list(range(len(item.options)))
    rng.shuffle(order)
    return QuizItem(
        item.topic_index,
        item.question,
        item.explanation,
        options=[item.options[i] for i in order],
        correct_index=order.index(item.correct_index),
    )


def fallback_question(outline: list[OutlineTopic], topic_index: int, n: int, rng: random.Random) -> QuizItem:
    """A simple question that needs no LLM: which topic is this key point from?"""
    topic = outline[topic_index]
    points = topic["key_points"] or [topic["summary"] or topic["title"]]
    point = points[n % len(points)]
    explanation = f'"{point}" is one of the key points of {topic["title"]}.'
    if len(outline) == 1:
        # Only one topic: a true/false question instead.
        return QuizItem(
            topic_index,
            f'True or false: "{point}" is part of {topic["title"]}.',
            explanation,
            options=["True", "False"],
            correct_index=0,
        )
    others = [i for i in range(len(outline)) if i != topic_index]
    choices = [topic_index] + rng.sample(others, min(OPTION_COUNT - 1, len(others)))
    rng.shuffle(choices)
    return QuizItem(
        topic_index,
        f'Which topic does this idea belong to? "{point}"',
        explanation,
        options=[outline[i]["title"] for i in choices],
        correct_index=choices.index(topic_index),
    )


def write_questions(
    llm: LLM,
    state: TeacherState,
    plan: list[int],
    avoid: list[str],
    rng: random.Random,
) -> tuple[list[QuizItem], str]:
    """One LLM call for the whole quiz; any slot it didn't fill gets a fallback question.

    Returns the questions and the LLM's note on the mix of question kinds.
    """
    outline = state["outline"]
    try:
        draft = llm.chat_json(
            messages(QUIZ_SYSTEM_PROMPT, quiz_prompt(state, plan, avoid)),
            DraftQuiz,
            request_timeout=20,
            max_attempts=1,
        )
        written = [clean_draft(q, len(outline)) for q in draft.questions]
        style_note = clean_text(draft.style_note)
    except LLMError:
        written, style_note = [], ""

    # Give each planned slot a question on its topic (the LLM's order doesn't matter).
    by_topic: dict[int, list[QuizItem]] = {}
    seen = {question.lower() for question in avoid}
    for item in written:
        if item and item.question.lower() not in seen:
            seen.add(item.question.lower())
            by_topic.setdefault(item.topic_index, []).append(item)

    items = []
    for n, topic_index in enumerate(plan):
        available = by_topic.get(topic_index)
        if available:
            items.append(shuffle_options(available.pop(0), rng))
        else:
            items.append(fallback_question(outline, topic_index, n, rng))
    return items, style_note


# ---------------------------------------------------------------------------
# One session's quiz
# ---------------------------------------------------------------------------


@dataclass
class QuizRecord:
    """The current quiz of a session, plus what's needed to write the next one."""

    items: list[QuizItem]
    focus_topics: list[int]
    attempt: int = 1
    asked: list[str] = field(default_factory=list)  # every question so far, to avoid repeats
    missed_topics: list[int] | None = None  # from the last marked quiz (None: not marked yet)
    style_note: str = ""


def weak_topics_for_new_quiz(state: TeacherState, previous: QuizRecord | None) -> list[int]:
    """What a new quiz should focus on."""
    if previous is None:
        return list(state["topics_to_improve"])  # the first quiz: mistakes in the lecture
    if previous.missed_topics is None:
        return previous.focus_topics  # the last quiz wasn't marked: keep its focus
    return previous.missed_topics  # what they got wrong in the last quiz (may be none)


def new_quiz(llm: LLM, state: TeacherState, previous: QuizRecord | None, rng: random.Random) -> QuizRecord:
    weak = weak_topics_for_new_quiz(state, previous)
    plan = plan_quiz_topics(len(state["outline"]), weak)
    avoid = previous.asked if previous else []
    items, style_note = write_questions(llm, state, plan, avoid, rng)
    return QuizRecord(
        items=items,
        focus_topics=sorted(set(weak) & set(plan)),
        attempt=previous.attempt + 1 if previous else 1,
        asked=avoid + [item.question for item in items],
        style_note=style_note,
    )


def restart_quiz(previous: QuizRecord) -> QuizRecord:
    """The same questions again; the old marks are forgotten."""
    return QuizRecord(
        items=previous.items,
        focus_topics=previous.focus_topics,
        attempt=previous.attempt + 1,
        asked=previous.asked,
        style_note=previous.style_note,
    )


def to_quiz(session_id: str, record: QuizRecord, outline: list[OutlineTopic]) -> Quiz:
    """What the frontend gets: the questions without their answers."""
    return Quiz(
        session_id=session_id,
        attempt=record.attempt,
        questions=[
            QuizQuestion(
                index=n,
                topic_index=item.topic_index,
                topic_title=outline[item.topic_index]["title"],
                kind=item.kind,
                question=item.question,
                options=item.options,
                code_answer=item.code_answer,
            )
            for n, item in enumerate(record.items)
        ],
        focus_topics=[topic(outline, i) for i in record.focus_topics],
        style_note=record.style_note,
    )


def topic(outline: list[OutlineTopic], index: int) -> Topic:
    return Topic(index=index, title=outline[index]["title"], summary=outline[index]["summary"])


# ---------------------------------------------------------------------------
# Checking the submitted answers
# ---------------------------------------------------------------------------


def answers_problem(record: QuizRecord, answers: list) -> str | None:
    """Why these answers can't be marked (None if they're fine)."""
    if len(answers) != len(record.items):
        return f"Expected {len(record.items)} answers, got {len(answers)}"
    for n, (item, answer) in enumerate(zip(record.items, answers)):
        if answer is None:
            continue
        if item.kind == "mcq" and not (
            isinstance(answer, int) and not isinstance(answer, bool) and 0 <= answer < len(item.options)
        ):
            return f"Answer {n + 1} must be an option number"
        if item.kind == "text" and not isinstance(answer, str):
            return f"Answer {n + 1} must be text"
    return None


# ---------------------------------------------------------------------------
# Grading typed answers (LLM)
# ---------------------------------------------------------------------------


class Grade(BaseModel):
    index: int = Field(description="The answer's number, as given")
    correct: bool
    feedback: str = Field(description="One sentence to the student: what was right or what was missing")


class Grades(BaseModel):
    grades: list[Grade]


GRADING_SYSTEM_PROMPT = (
    "You mark a student's short typed quiz answers, kindly but fairly. Write plain text: "
    "no markdown, no [bracketed] voice tags."
)


def grading_prompt(to_grade: list[tuple[int, QuizItem, str]]) -> str:
    lines = [
        "Mark each answer as correct or not.",
        "- Correct if it shows the key idea of the model answer. Different wording, extra "
        "detail and small spelling slips don't matter.",
        "- Code: correct if it would work and does what was asked; style doesn't matter.",
        "- Language answers (grammar, vocabulary, translation): the form asked for must be "
        "right, since that's what is being tested.",
        "- feedback: one sentence to the student (\"you\"): what was right, or what was missing.",
        "",
    ]
    for n, item, answer in to_grade:
        lines += [
            f"Answer {n}:",
            f"  Question: {item.question}",
            f"  Model answer: {item.expected_answer}",
            f"  Student's answer: {answer}",
            "",
        ]
    lines.append('Reply with JSON only: {"grades": [{"index": 0, "correct": true, "feedback": "..."}]}')
    return "\n".join(lines)


STOP_WORDS = {
    "the", "and", "that", "this", "with", "from", "they", "their", "there", "which", "when",
    "what", "into", "than", "then", "them", "have", "will", "would", "because", "about",
}


def key_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[\w']+", text.lower()) if len(w) >= 4 and w not in STOP_WORDS}


def keyword_grade(item: QuizItem, answer: str) -> tuple[bool, str]:
    """The fallback: correct if the answer has at least half the model answer's key words."""
    wanted = key_words(item.expected_answer) or set(re.findall(r"[\w']+", item.expected_answer.lower()))
    found = wanted & set(re.findall(r"[\w']+", answer.lower()))
    correct = bool(wanted) and len(found) * 2 >= len(wanted)
    return correct, "Checked automatically: compare your answer with the model answer."


def grade_text_answers(llm: LLM, to_grade: list[tuple[int, QuizItem, str]]) -> dict[int, tuple[bool, str]]:
    """{answer number: (correct, feedback)} for every typed answer, in one LLM call."""
    if not to_grade:
        return {}
    grades: dict[int, tuple[bool, str]] = {}
    try:
        reply = llm.chat_json(
            messages(GRADING_SYSTEM_PROMPT, grading_prompt(to_grade)),
            Grades,
            temperature=0,
            request_timeout=15,
            max_attempts=1,
        )
        wanted = {n for n, _, _ in to_grade}
        for grade in reply.grades:
            if grade.index in wanted:
                grades[grade.index] = (grade.correct, clean_text(grade.feedback))
    except LLMError:
        pass
    # Anything the LLM didn't grade is checked by key words.
    for n, item, answer in to_grade:
        if n not in grades:
            grades[n] = keyword_grade(item, answer)
    return grades


# ---------------------------------------------------------------------------
# Marking
# ---------------------------------------------------------------------------


def mark_quiz(
    llm: LLM,
    session_id: str,
    record: QuizRecord,
    answers: list[int | str | None],
    outline: list[OutlineTopic],
) -> QuizResult:
    """Score the answers, and remember the missed topics for the next new quiz.

    Check them with answers_problem() first.
    """
    typed = {
        n: answer.strip()[:MAX_ANSWER_CHARS]
        for n, (item, answer) in enumerate(zip(record.items, answers))
        if item.kind == "text" and isinstance(answer, str) and answer.strip()
    }
    grades = grade_text_answers(llm, [(n, record.items[n], text) for n, text in typed.items()])

    review = []
    for n, (item, answer) in enumerate(zip(record.items, answers)):
        if item.kind == "text":
            # A blank answer is wrong without asking the LLM.
            correct, feedback = grades.get(n, (False, "You didn't answer this one."))
            review.append(
                QuizReview(
                    index=n,
                    topic_index=item.topic_index,
                    kind="text",
                    question=item.question,
                    code_answer=item.code_answer,
                    answer_text=typed.get(n),
                    expected_answer=item.expected_answer,
                    correct=correct,
                    feedback=feedback,
                    explanation=item.explanation,
                )
            )
        else:
            review.append(
                QuizReview(
                    index=n,
                    topic_index=item.topic_index,
                    question=item.question,
                    options=item.options,
                    chosen_index=answer,
                    correct_index=item.correct_index,
                    correct=answer == item.correct_index,
                    explanation=item.explanation,
                )
            )
    missed = sorted({r.topic_index for r in review if not r.correct})
    record.missed_topics = missed
    score = sum(r.correct for r in review)
    return QuizResult(
        session_id=session_id,
        score=score,
        total=len(review),
        review=review,
        topics_to_improve=[topic(outline, i) for i in missed],
        feedback=quiz_feedback(score, len(review), [outline[i]["title"] for i in missed]),
    )


def quiz_feedback(score: int, total: int, missed_titles: list[str]) -> str:
    if score == total:
        return "A perfect score! You understood every topic. Try new questions to keep it fresh."
    lead = "Nice work." if score >= total * 0.7 else "Good effort." if score >= total * 0.4 else "Keep going."
    return (
        f"{lead} Focus on {join_titles(missed_titles)}: replay those topics, "
        "then try new questions aimed at them."
    )


def join_titles(titles: list[str]) -> str:
    if len(titles) <= 1:
        return "".join(titles)
    return ", ".join(titles[:-1]) + " and " + titles[-1]
