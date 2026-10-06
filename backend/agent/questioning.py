"""Step 8: ask a question, grade the answer, and respond.

    explain part -> ask_question -> (student answers) -> evaluate_answer
                                         ^                     |
                                         |------ hint ---------|  (wrong, a try left)
                                                               |
                         praise + explanation / reveal answer -+-> continue lecture

The rule for the response is feedback_kind() from state.py:
- correct (first try or retry)  -> praise + short explanation
- wrong, a try left             -> hint, ask again
- wrong on the last try         -> give the correct answer + explanation
"""

from pydantic import BaseModel, Field

from agent.explaining import enter_topic, save_progress
from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.state import (
    MAX_ATTEMPTS,
    Mode,
    OutlineTopic,
    PendingQuestion,
    TeacherState,
    TopicScore,
    feedback_kind,
)


class Question(BaseModel):
    question: str = Field(description="The question, as the teacher will say it aloud")
    expected_answer: str = Field(description="A short model answer, used for grading")
    explanation: str = Field(description="1-2 sentences on why that is the answer")


class AnswerFeedback(BaseModel):
    correct: bool
    response: str = Field(description="What the teacher says to the student now")


# ---------------------------------------------------------------------------
# Asking
# ---------------------------------------------------------------------------


def part_just_explained(state: TeacherState) -> list[str]:
    """The segments explained since the previous question (or the start of the topic).

    By the time the question is asked, segment_index has moved to the end of that part.
    """
    end = state["segment_index"]
    start = max((p for p in state["question_points"] if p < end), default=0)
    return state["segments"][start:end]


def ask_prompt(state: TeacherState) -> str:
    topic = state["outline"][state["current_topic"]]
    part = " ".join(part_just_explained(state)) or topic["summary"]
    return "\n".join(
        [
            f'You just explained this part of the topic "{topic["title"]}":',
            f'"{part}"',
            "",
            "Ask the student ONE question to check they understood it.",
            "- Only ask about what you just explained.",
            "- It should need thinking, not just repeating a word: not a yes/no question.",
            "- The student types the answer, so it must be answerable in 1-2 sentences.",
            "- Say it in your own voice, as you would aloud. One or two sentences.",
            "Also give a short expected answer and a 1-2 sentence explanation of why it's right.",
        ]
    )


def generate_question(llm: LLM, state: TeacherState) -> PendingQuestion:
    personality = get_personality(state["environment"])
    topic = state["outline"][state["current_topic"]]
    try:
        question = llm.chat_json(
            messages(build_system_prompt(personality), ask_prompt(state)), Question
        )
        if question.question.strip() and question.expected_answer.strip():
            return PendingQuestion(
                question=question.question.strip(),
                expected_answer=question.expected_answer.strip(),
                explanation=question.explanation.strip(),
            )
    except LLMError:
        pass
    return fallback_question(topic)


def fallback_question(topic: OutlineTopic) -> PendingQuestion:
    summary = topic["summary"] or ", ".join(topic["key_points"]) or topic["title"]
    return PendingQuestion(
        question=f"In your own words, what is the main idea of {topic['title']}?",
        expected_answer=summary,
        explanation=summary,
    )


def make_ask_question_node(llm: LLM):
    """The 'ask_question' node: asks a question about the part just explained."""

    def ask_question(state: TeacherState) -> dict:
        question = generate_question(llm, state)
        return {
            "pending_question": question,
            "attempts": 0,
            "student_input": None,
            "speech": [question["question"]],
            "mode": Mode.AWAITING_ANSWER,
            "history": [{"role": "teacher", "text": question["question"]}],
        }

    return ask_question


# ---------------------------------------------------------------------------
# Grading and responding
# ---------------------------------------------------------------------------


def feedback_prompt(state: TeacherState, answer: str) -> str:
    question = state["pending_question"]
    last_try = state["attempts"] + 1 >= MAX_ATTEMPTS
    if last_try:
        if_wrong = (
            "This was their last try. Kindly tell them it's not quite right, then give "
            "the correct answer and explain why, using the explanation above."
        )
    else:
        if_wrong = (
            "Do NOT give the answer away. Give a short hint that nudges them toward it, "
            "building on what they wrote, and ask them to try again."
        )

    return "\n".join(
        [
            f'You asked: "{question["question"]}"',
            f'Expected answer: "{question["expected_answer"]}"',
            f'Explanation: "{question["explanation"]}"',
            f'The student answered: "{answer}"',
            "",
            "First decide if the answer is correct. Judge the meaning, not the wording: "
            "accept answers that capture the key idea, even if phrased differently, "
            "incomplete in small details, or misspelled. \"I don't know\" is not correct.",
            "",
            "Then write what you say to the student now (2-3 sentences, spoken, in your voice):",
            "- If correct: praise them, then briefly explain why it's right, using the explanation above.",
            f"- If not correct: {if_wrong}",
        ]
    )


def fallback_feedback(question: PendingQuestion, kind: str) -> str:
    if kind == "praise":
        return f"That's right! {question['explanation']}"
    if kind == "hint":
        return "Not quite. Have another think about what we just covered, and try again."
    return f"Not quite. The answer is: {question['expected_answer']}. {question['explanation']}"


def record_score(performance: dict[int, TopicScore], topic: int, correct: bool) -> dict[int, TopicScore]:
    score = performance.get(topic, TopicScore(correct=0, incorrect=0))
    key = "correct" if correct else "incorrect"
    return {**performance, topic: {**score, key: score[key] + 1}}


def make_evaluate_answer_node(llm: LLM):
    """The 'evaluate_answer' node: grades state["student_input"] and responds."""

    def evaluate_answer(state: TeacherState) -> dict:
        question = state["pending_question"]
        answer = (state["student_input"] or "").strip()
        personality = get_personality(state["environment"])
        student_line = [{"role": "student", "text": answer}]

        try:
            result = llm.chat_json(
                messages(build_system_prompt(personality), feedback_prompt(state, answer)),
                AnswerFeedback,
            )
        except LLMError:
            # Can't grade right now: give the answer, don't count it, and move on.
            text = fallback_feedback(question, "reveal").replace("Not quite. ", "", 1)
            return {
                "speech": [text],
                "pending_question": None,
                "attempts": 0,
                "mode": Mode.FEEDBACK,
                "history": student_line + [{"role": "teacher", "text": text}],
            }

        kind = feedback_kind(result.correct, state["attempts"])
        text = result.response.strip() or fallback_feedback(question, kind)
        update = {
            "speech": [text],
            "history": student_line + [{"role": "teacher", "text": text}],
        }

        if kind == "hint":
            # Same question, one more try.
            return update | {"attempts": state["attempts"] + 1, "mode": Mode.AWAITING_ANSWER}

        # praise or reveal: the question is done, the lecture continues.
        return update | {
            "pending_question": None,
            "attempts": 0,
            "mode": Mode.FEEDBACK,
            "performance": record_score(state["performance"], state["current_topic"], kind == "praise"),
        }

    return evaluate_answer


# ---------------------------------------------------------------------------
# Moving on
# ---------------------------------------------------------------------------


def topic_finished(state: TeacherState) -> bool:
    """True once every part of the current topic has been explained and asked about."""
    return bool(state["segments"]) and state["segment_index"] >= len(state["segments"])


def next_topic(state: TeacherState) -> dict:
    """The 'next_topic' node: marks the topic done and moves on.

    Goes to the first topic not finished yet (resuming it if it was left
    halfway), so replaying an old topic brings the student back to where they
    were. current_topic becomes None when every topic is done: the lecture is over.
    """
    completed = sorted(set(state["completed_topics"]) | {state["current_topic"]})
    progress = save_progress(state)
    remaining = [i for i in range(len(state["outline"])) if i not in completed]
    if not remaining:
        return {"completed_topics": completed, "current_topic": None, "topic_progress": progress}
    return {"completed_topics": completed} | enter_topic(
        state | {"completed_topics": completed}, remaining[0], progress
    )
