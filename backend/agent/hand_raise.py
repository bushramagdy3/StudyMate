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
from agent.questioning import next_topic
from agent.state import Mode, TeacherState
from pydantic import BaseModel, Field

RECENT_HISTORY = 6


class StudentQuestionAnswer(BaseModel):
    answer: str = Field(description="The spoken answer to the student's question")
    slide: int | None = Field(
        default=None,
        description="The relevant slide number from the current topic",
    )

# What Regina says when she sees a raised hand. Fixed lines, so there's no LLM wait.
HAND_RAISE_REPLIES = {
    "professor": "[reassuring] Yes, go ahead. What question would you like to raise?",
    "tutor": "[reassuring] Of course. What are you wondering about?",
    "study friend": "[thoughtful] Yeah, tell me what part feels confusing.",
}


# At the end of a topic, an answered question should lead into another chance to
# ask, rather than resuming a lecture that has already finished.
TOPIC_EXIT_FOLLOW_UPS = {
    "professor": "[reassuring] Is there anything else you would like to ask about this topic?",
    "tutor": "[reassuring] Is there anything else you want to clear up before we move on?",
    "study friend": "[thoughtful] Anything else about this before we move on?",
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
        "topic_exit_pending": False,
        "segment_index": max(start, min(start + segment_index, part_end - 1)),
        "speech": [HAND_RAISE_REPLIES[get_personality(state["environment"]).role]],
    }


def student_question_prompt(state: TeacherState, question: str) -> str:
    topic = state["outline"][state["current_topic"]]
    source_slides = topic["source_slides"]
    other_topics = [
        item["title"]
        for index, item in enumerate(state["outline"])
        if index != state["current_topic"]
    ]
    lines = [
        f'The student raised their hand and asked: "{question}"',
        "",
        f'You are currently teaching "{topic["title"]}", from these slides:',
        slides_text(state["lecture"], topic["source_slides"]) or "(no slide text)",
        "",
        "Topics in this lecture, in order: " + ", ".join(t["title"] for t in state["outline"]),
        "Current topic slides: " + ", ".join(str(slide) for slide in source_slides),
        "",
    ]

    recent = state["history"][-RECENT_HISTORY:]
    if recent:
        lines += ["Recent conversation:"]
        lines += [f"{line['role'].capitalize()}: {line['text']}" for line in recent]
        lines += [""]

    lines += [
        "Answer their question in 2 to 4 spoken sentences.",
        "- Questions about any slide in the CURRENT topic are allowed, including an earlier slide. Choose that relevant slide number.",
        "- If the question is about another topic, do not teach it yet. Say that you can answer it once this topic is finished and they choose that topic from the outline.",
        "- If the lecture doesn't cover it, say so briefly and give a short general answer.",
        "- If it is unrelated to the lecture, answer in one sentence and gently bring them back.",
        "- slide must be one of the current topic slides. For an out-of-topic question, use the current slide.",
    ]
    if state.get("topic_exit_pending"):
        lines.append(
            '- This is final question time for the topic. Do not say "back to where we were" '
            "or imply that the lecture will resume. Give only the answer; the app will ask whether "
            "the student has anything else to ask before moving on."
        )
    else:
        lines.append('- End with a short line to get back to the lecture, like "Okay, back to where we were."')
    if other_topics:
        lines.append("Other topics that must wait: " + ", ".join(other_topics))
    return "\n".join(lines)


def fallback_slide(state: TeacherState, question: str) -> int | None:
    """Choose a reasonable in-topic slide when the structured answer cannot."""
    slides = state["outline"][state["current_topic"]]["source_slides"]
    if not slides:
        return state.get("current_slide")
    current = state.get("current_slide")
    earlier = any(word in question.lower() for word in ("previous", "earlier", "last slide", "before"))
    if earlier and current in slides:
        position = slides.index(current)
        if position > 0:
            return slides[position - 1]
    return current if current in slides else slides[0]


def is_no_question(text: str) -> bool:
    words = " ".join(text.lower().strip().split())
    no_answers = {
        "no",
        "nope",
        "nah",
        "nothing",
        "nothing else",
        "none",
        "not really",
        "not at the moment",
        "no questions",
        "no more questions",
        "all good",
        "all clear",
        "all set",
        "i'm good",
        "im good",
        "i'm all set",
        "im all set",
        "that's all",
        "thats all",
        "that is all",
        "i think that's it",
        "i think thats it",
        "that's it for now",
        "thats it for now",
        "i don't have any questions",
        "i dont have any questions",
    }
    return words in no_answers or words.startswith(("no ", "nothing "))


def asked_about_another_topic(state: TeacherState, question: str) -> bool:
    question = question.lower()
    current = state["current_topic"]
    return any(
        index != current and topic["title"].lower() in question
        for index, topic in enumerate(state["outline"])
    )


def make_answer_student_question_node(llm: LLM):
    """The 'answer_student_question' node: answers state["student_input"].

    After a regular hand-raise answer plays, "continue" goes back to the
    explanation. Final-topic question time remains open until the student says
    they have no more questions.
    """

    def answer_student_question(state: TeacherState) -> dict:
        question = (state["student_input"] or "").strip()
        personality = get_personality(state["environment"])

        if state.get("topic_exit_pending") and is_no_question(question):
            return next_topic(state) | {
                "history": [{"role": "student", "text": question}],
            }

        slide = fallback_slide(state, question)
        if asked_about_another_topic(state, question):
            answer = (
                "[reassuring] I can answer that once we finish this topic. "
                "Choose that topic from the outline when we are done, and we will go through it then."
            )
            if state.get("topic_exit_pending"):
                answer = f"{answer} {TOPIC_EXIT_FOLLOW_UPS[personality.role]}"
            return {
                "speech": [answer],
                "speech_slides": [slide] if slide is not None else [],
                "current_slide": slide,
                "mode": (
                    Mode.AWAITING_STUDENT_QUESTION
                    if state.get("topic_exit_pending")
                    else Mode.ANSWERING_STUDENT
                ),
                "history": [{"role": "student", "text": question}, {"role": "teacher", "text": answer}],
            }

        try:
            reply = llm.chat_json(
                messages(build_system_prompt(personality), student_question_prompt(state, question)),
                StudentQuestionAnswer,
                request_timeout=20,
                max_attempts=1,
            )
            answer = reply.answer.strip()
            source_slides = state["outline"][state["current_topic"]]["source_slides"]
            if reply.slide in source_slides:
                slide = reply.slide
        except LLMError:
            answer = (
                "Good question! I can't answer that right now, but we can stay with this topic "
                "and work through anything else you are unsure about."
                if state.get("topic_exit_pending")
                else "Good question! I can't answer that right now, so let's keep going and come back to it."
            )

        if state.get("topic_exit_pending"):
            answer = f"{answer.rstrip()} {TOPIC_EXIT_FOLLOW_UPS[personality.role]}"

        return {
            "speech": [answer],
            "speech_slides": [slide] if slide is not None else [],
            "current_slide": slide,
            "mode": (
                Mode.AWAITING_STUDENT_QUESTION
                if state.get("topic_exit_pending")
                else Mode.ANSWERING_STUDENT
            ),
            "history": [{"role": "student", "text": question}, {"role": "teacher", "text": answer}],
        }

    return answer_student_question
