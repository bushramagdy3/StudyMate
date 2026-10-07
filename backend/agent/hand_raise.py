"""Step 9: the student raises their hand, asks a question, and the lecture resumes.

A hand can only be raised while the teacher is explaining (not during
feedback, questions, or answers to the student's questions).

    explaining  --raise_hand-->  "Yes? Go ahead."  (waits for the question)
                                         |
                           student types their question
                                         |
                              answer_student_question
                                         |
                 continue -> replay from the interrupted segment
"""

from agent.explaining import next_stop
from agent.llm import LLM, LLMError, messages
from agent.personalities import build_system_prompt, get_personality
from agent.planning import slides_text
from agent.state import Mode, TeacherState

RECENT_HISTORY = 6

# What Regina says when she sees a raised hand. Fixed lines, so there's no LLM wait.
HAND_RAISE_REPLIES = {
    "professor": "[reassuring] Yes, go ahead. What question would you like to raise?",
    "tutor": "[reassuring] Of course. What are you wondering about?",
    "study friend": "[thoughtful] Yeah, tell me what part feels confusing.",
}


def raise_hand(state: TeacherState, segment_index: int) -> dict:
    """The student raised their hand. No LLM call: Regina just invites the question.

    segment_index is the position inside the speech the frontend was playing.
    Ignored unless the teacher is explaining.
    """
    if state["mode"] != Mode.EXPLAINING:
        return {}

    # Resume from the segment that was playing, but never past the end of this part.
    start = state["segment_index"]
    part_end = next_stop(start, state["question_points"], len(state["segments"]))
    return {
        "mode": Mode.AWAITING_STUDENT_QUESTION,
        "segment_index": max(start, min(start + segment_index, part_end - 1)),
        "speech": [HAND_RAISE_REPLIES[get_personality(state["environment"]).role]],
    }


def student_question_prompt(state: TeacherState, question: str) -> str:
    topic = state["outline"][state["current_topic"]]
    lines = [
        f'The student raised their hand and asked: "{question}"',
        "",
        f'You are currently teaching "{topic["title"]}", from these slides:',
        slides_text(state["lecture"], topic["source_slides"]) or "(no slide text)",
        "",
        "Topics in this lecture, in order: " + ", ".join(t["title"] for t in state["outline"]),
        "",
    ]

    recent = state["history"][-RECENT_HISTORY:]
    if recent:
        lines += ["Recent conversation:"]
        lines += [f"{line['role'].capitalize()}: {line['text']}" for line in recent]
        lines += [""]

    lines += [
        "Answer their question in 2 to 4 spoken sentences.",
        "- Base it on the lecture. If the lecture doesn't cover it, say so briefly and give a short general answer.",
        "- If it's about a topic that comes later in the lecture, give a one-sentence answer and say you'll cover it soon.",
        "- If it's unrelated to the lecture, answer in one sentence and gently bring them back.",
        '- End with a short line to get back to the lecture, like "Okay, back to where we were."',
    ]
    return "\n".join(lines)


def make_answer_student_question_node(llm: LLM):
    """The 'answer_student_question' node: answers state["student_input"].

    After the answer plays, "continue" goes back to the explanation (Step 11).
    """

    def answer_student_question(state: TeacherState) -> dict:
        question = (state["student_input"] or "").strip()
        personality = get_personality(state["environment"])
        try:
            answer = llm.chat(
                messages(build_system_prompt(personality), student_question_prompt(state, question))
            )
        except LLMError:
            answer = "Good question! I can't answer that right now, so let's keep going and come back to it."

        return {
            "speech": [answer],
            "mode": Mode.ANSWERING_STUDENT,
            "history": [{"role": "student", "text": question}, {"role": "teacher", "text": answer}],
        }

    return answer_student_question
