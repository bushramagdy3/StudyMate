import json
import random

import httpx
import pytest

from agent import llm as llm_module
from agent.contract import (
    AnswerEvent,
    ContinueEvent,
    Environment,
    GoToTopicEvent,
    LectureChunk,
    QuestionEvent,
    StartSessionRequest,
)
from agent.llm import LLM
from agent.quiz import (
    STYLE_GUIDE,
    DraftQuestion,
    QuizRecord,
    answers_problem,
    clean_draft,
    keyword_grade,
    mark_quiz,
    new_quiz,
    plan_quiz_topics,
    quiz_prompt,
    restart_quiz,
    to_quiz,
)
from agent.state import Mode, all_topics_completed, initial_state, to_response
from agent.teacher import EventNotAllowed, SessionNotFound, Teacher
from tests.test_teacher import LECTURE, PLAN, text_reply

OUTLINE = [
    {"title": "Pipelining", "summary": "No waiting.", "key_points": ["overlap", "order kept"], "source_slides": [1]},
    {"title": "Head-of-Line Blocking", "summary": "Slow blocks fast.", "key_points": ["order"], "source_slides": [2]},
    {"title": "Multiplexing", "summary": "Many streams.", "key_points": ["streams"], "source_slides": [2]},
]


def make_state(**fields):
    request = StartSessionRequest(environment=Environment.CAFE, lecture=LECTURE)
    state = initial_state("abc", request) | {
        "outline": OUTLINE,
        "completed_topics": [0, 1, 2],
        "current_topic": None,
        "mode": Mode.ENDED,
    }
    return state | fields


def draft(topic_index, n=0, correct=0):
    return {
        "topic_index": topic_index,
        "question": f"Q{n} about topic {topic_index}?",
        "options": [f"right {n}", f"wrong a{n}", f"wrong b{n}", f"wrong c{n}"],
        "correct_index": correct,
        "explanation": f"Because {n}.",
    }


def quiz_reply_for(prompt):
    """Writes exactly the questions the prompt asks for, e.g. "2 on topic 1"."""
    wanted = []
    for part in prompt.split("Write exactly ")[1].split(".")[0].split(": ")[1].split(", "):
        count, _, _, topic = part.split(" ")
        wanted += [int(topic)] * int(count)
    return {"questions": [draft(t, n) for n, t in enumerate(wanted)]}


def text_draft(topic_index, n=0, code=False):
    return {
        "topic_index": topic_index,
        "kind": "text",
        "question": f"T{n}: explain topic {topic_index}.",
        "expected_answer": "Requests are sent without waiting for each response.",
        "code_answer": code,
        "explanation": f"Because {n}.",
    }


def mixed_reply_for(prompt):
    """Like quiz_reply_for, but every second question is a typed answer."""
    questions = quiz_reply_for(prompt)["questions"]
    for n, q in enumerate(questions):
        if n % 2:
            questions[n] = text_draft(q["topic_index"], n)
    return {"style_note": "A mix: explaining ideas in your own words matters here.", "questions": questions}


def grades_reply_for(prompt):
    """Grades every typed answer: correct if the student's answer contains "right"."""
    grades = []
    for block in prompt.split("Answer ")[1:]:
        number, rest = block.split(":", 1)
        if not number.isdigit():
            continue
        student = rest.split("Student's answer:")[1].split("\n")[0]
        grades.append({"index": int(number), "correct": "right" in student, "feedback": f"Feedback {number}."})
    return {"grades": grades}


def fake_llm(reply=None, status=200):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        prompt = body["messages"][1]["content"]
        sent.append(prompt)
        if status != 200:
            return httpx.Response(status)
        content = reply(prompt) if callable(reply) else reply
        return text_reply(json.dumps(content))

    return LLM("key", "model", transport=httpx.MockTransport(handler)), sent


NO_LLM = None  # set below: an LLM that always fails (multiple choice needs none)


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm_module, "RETRY_DELAY", 0)


NO_LLM, _ = fake_llm(status=503)


# --- which topics the questions are about -------------------------------------


def test_no_mistakes_is_balanced():
    assert plan_quiz_topics(3, []) == [0, 0, 1, 1, 2]
    assert plan_quiz_topics(5, []) == [0, 1, 2, 3, 4]
    assert len(plan_quiz_topics(20, [])) == 10  # capped


def test_mistakes_get_two_questions_and_every_other_topic_one():
    assert plan_quiz_topics(4, [2]) == [0, 1, 2, 2, 3]
    assert plan_quiz_topics(8, [1, 2]) == [0, 1, 1, 2, 2, 3, 4, 5, 6, 7]


def test_every_topic_is_covered_even_when_all_are_weak():
    plan = plan_quiz_topics(6, list(range(6)))
    assert set(plan) == set(range(6))
    assert len(plan) == 10


def test_a_short_lecture_still_gets_enough_questions():
    assert plan_quiz_topics(2, [1]) == [0, 0, 1, 1, 1]
    assert plan_quiz_topics(1, []) == [0] * 5


def test_bad_topic_indexes_are_ignored():
    assert plan_quiz_topics(3, [7, -1]) == plan_quiz_topics(3, [])


# --- writing the questions ----------------------------------------------------


def test_prompt_asks_for_the_planned_questions_and_avoids_old_ones():
    prompt = quiz_prompt(make_state(), [0, 1, 1, 2], avoid=["Old question?"])
    assert "Write exactly 4 questions: 1 on topic 0, 2 on topic 1, 1 on topic 2." in prompt
    assert "Head-of-line blocking: one slow response blocks the rest." in prompt  # slide text
    assert "- Old question?" in prompt


def test_broken_questions_are_dropped():
    good = DraftQuestion(**draft(0))
    assert clean_draft(good, 3) is not None
    assert clean_draft(good.model_copy(update={"options": ["a", "b", "c"]}), 3) is None
    assert clean_draft(good.model_copy(update={"options": ["a", "a", "b", "c"]}), 3) is None
    assert clean_draft(good.model_copy(update={"correct_index": 4}), 3) is None
    assert clean_draft(good.model_copy(update={"topic_index": 3}), 3) is None
    tagged = clean_draft(good.model_copy(update={"question": "[emphasis] Why?"}), 3)
    assert tagged.question == "Why?"  # no voice tags in written text


def test_first_quiz_focuses_on_lecture_mistakes():
    llm, sent = fake_llm(quiz_reply_for)
    record = new_quiz(llm, make_state(topics_to_improve=[1]), None, random.Random(0))

    assert [item.topic_index for item in record.items] == [0, 0, 1, 1, 2]  # lecture order
    assert record.focus_topics == [1]
    assert record.attempt == 1
    for item in record.items:
        assert item.options[item.correct_index].startswith("right")  # still right after shuffling
    assert "2 on topic 1" in sent[0]


def test_first_quiz_without_mistakes_is_balanced():
    llm, _ = fake_llm(quiz_reply_for)
    record = new_quiz(llm, make_state(), None, random.Random(0))
    assert sorted(item.topic_index for item in record.items) == [0, 0, 1, 1, 2]
    assert record.focus_topics == []


def test_llm_failure_uses_simple_questions():
    llm, _ = fake_llm(status=503)
    record = new_quiz(llm, make_state(), None, random.Random(0))
    assert len(record.items) == 5
    for item in record.items:
        assert "Which topic does this idea belong to?" in item.question
        assert item.options[item.correct_index] == OUTLINE[item.topic_index]["title"]


def test_missing_questions_are_filled_in():
    llm, _ = fake_llm({"questions": [draft(0)]})  # only 1 of 5
    record = new_quiz(llm, make_state(), None, random.Random(0))
    assert len(record.items) == 5
    assert sum(item.question.startswith("Q0") for item in record.items) == 1


def test_one_topic_lecture_fallback_is_true_or_false():
    llm, _ = fake_llm(status=503)
    record = new_quiz(llm, make_state(outline=OUTLINE[:1], completed_topics=[0]), None, random.Random(0))
    assert record.items[0].options == ["True", "False"]


# --- marking ------------------------------------------------------------------


def make_record():
    llm, _ = fake_llm(quiz_reply_for)
    return new_quiz(llm, make_state(topics_to_improve=[1]), None, random.Random(0))


def test_marking_scores_and_lists_topics_to_improve():
    record = make_record()
    answers = [item.correct_index for item in record.items]
    wrong = [i for i, item in enumerate(record.items) if item.topic_index == 2][0]
    answers[wrong] = (answers[wrong] + 1) % 4
    answers[0] = None  # left blank counts as wrong (topic 0)

    result = mark_quiz(NO_LLM, "abc", record, answers, OUTLINE)

    assert (result.score, result.total) == (3, 5)
    assert [t.title for t in result.topics_to_improve] == ["Pipelining", "Multiplexing"]
    assert not result.review[wrong].correct
    assert result.review[wrong].correct_index == record.items[wrong].correct_index
    assert result.review[wrong].explanation.startswith("Because")
    assert "Pipelining and Multiplexing" in result.feedback


def test_perfect_score_has_nothing_to_improve():
    record = make_record()
    result = mark_quiz(NO_LLM, "abc", record, [item.correct_index for item in record.items], OUTLINE)
    assert result.score == result.total
    assert result.topics_to_improve == []
    assert "perfect" in result.feedback.lower()


def test_quiz_sent_to_the_frontend_has_no_answers():
    quiz = to_quiz("abc", make_record(), OUTLINE)
    data = quiz.model_dump()
    assert "correct_index" not in json.dumps(data) and "explanation" not in json.dumps(data)
    assert quiz.questions[2].topic_title == "Head-of-Line Blocking"
    assert [t.title for t in quiz.focus_topics] == ["Head-of-Line Blocking"]


# --- new and restarted quizzes ------------------------------------------------


def test_new_quiz_focuses_on_what_was_missed_last_time_and_avoids_repeats():
    first = make_record()
    answers = [item.correct_index if item.topic_index != 2 else None for item in first.items]
    mark_quiz(NO_LLM, "abc", first, answers, OUTLINE)  # missed topic 2 only

    llm, sent = fake_llm(quiz_reply_for)
    second = new_quiz(llm, make_state(topics_to_improve=[1]), first, random.Random(0))

    assert second.focus_topics == [2]
    assert [item.topic_index for item in second.items].count(2) >= 2
    assert second.attempt == 2
    assert first.items[0].question in sent[0]  # told to avoid earlier questions


def test_new_quiz_after_a_perfect_score_is_balanced():
    first = make_record()
    mark_quiz(NO_LLM, "abc", first, [item.correct_index for item in first.items], OUTLINE)
    llm, _ = fake_llm(quiz_reply_for)
    second = new_quiz(llm, make_state(topics_to_improve=[1]), first, random.Random(0))
    assert second.focus_topics == []


def test_restart_keeps_the_same_questions():
    first = make_record()
    mark_quiz(NO_LLM, "abc", first, [None] * len(first.items), OUTLINE)
    again = restart_quiz(first)
    assert again.items == first.items
    assert again.attempt == 2
    assert again.missed_topics is None  # old marks forgotten


# --- unlocking ----------------------------------------------------------------


def test_quiz_unlocks_when_every_topic_is_completed():
    assert all_topics_completed(make_state())
    assert to_response(make_state()).quiz_available
    assert not to_response(make_state(completed_topics=[0, 2])).quiz_available
    assert not all_topics_completed(make_state(outline=[], completed_topics=[]))


# --- through the Teacher ------------------------------------------------------


def featherless_with_quiz():
    """The lecture fake from test_teacher, plus quiz writing and grading."""
    calls = {"explain": 0, "quiz": 0}

    def handler(request):
        full = json.loads(request.content)["messages"][1]["content"]
        if "Write a quiz about this lecture" in full:
            calls["quiz"] += 1
            return text_reply(json.dumps(mixed_reply_for(full)))
        if "Mark each answer" in full:
            return text_reply(json.dumps(grades_reply_for(full)))
        if "Split this lecture" in full:
            return text_reply(json.dumps(PLAN))
        if "Write the explanation" in full:
            calls["explain"] += 1
            n = calls["explain"]
            return text_reply(json.dumps({"segments": [f"e{n}-s0"], "question_after": [1]}))
        if "Ask the student ONE question" in full:
            return text_reply(json.dumps({"question": "Why?", "expected_answer": "x", "explanation": "y"}))
        if "The student answered" in full:
            correct = '"right' in full.split("The student answered:")[1]
            return text_reply(json.dumps({"correct": correct, "response": "ok"}))
        return text_reply("Okay.")

    return httpx.MockTransport(handler), calls


@pytest.fixture
def teacher():
    transport, _ = featherless_with_quiz()
    return Teacher(llm=LLM("key", "model", transport=transport), rng=random.Random(0))


def finish_lecture(teacher, first_answer="right"):
    session = teacher.start_session(StartSessionRequest(environment=Environment.CAFE, lecture=LECTURE)).session_id
    send = lambda event: teacher.send_event(session, event)
    send(ContinueEvent())  # intro done
    for topic in (0, 1):
        send(GoToTopicEvent(topic_index=topic))
        send(ContinueEvent())
        response = send(AnswerEvent(text=first_answer if topic == 1 else "right"))
        if response.awaiting.value == "answer":
            send(AnswerEvent(text="right"))
        send(ContinueEvent())  # final-question prompt
        done = send(QuestionEvent(text="no"))
    assert done.quiz_available
    return session


def test_quiz_is_locked_until_every_topic_is_completed(teacher):
    session = teacher.start_session(StartSessionRequest(environment=Environment.CAFE, lecture=LECTURE)).session_id
    with pytest.raises(EventNotAllowed):
        teacher.start_quiz(session)


def test_quiz_after_lecture_mistakes_focuses_on_them(teacher):
    session = finish_lecture(teacher, first_answer="no")  # wrong once on topic 1, right on retry

    quiz = teacher.start_quiz(session, "new")
    topics = [q.topic_index for q in quiz.questions]
    assert [t.index for t in quiz.focus_topics] == [1]
    assert topics.count(1) > topics.count(0) >= 1


def test_take_restart_and_reprompt_through_the_teacher(teacher):
    session = finish_lecture(teacher)
    quiz = teacher.start_quiz(session, "new")
    assert quiz.attempt == 1 and quiz.focus_topics == []  # no mistakes: balanced

    result = teacher.submit_quiz(session, [None] * len(quiz.questions))
    assert result.score == 0 and result.total == len(quiz.questions)
    assert {t.index for t in result.topics_to_improve} == {0, 1}

    again = teacher.start_quiz(session, "restart")
    assert [q.question for q in again.questions] == [q.question for q in quiz.questions]
    assert again.attempt == 2

    with pytest.raises(EventNotAllowed):
        teacher.submit_quiz(session, [0])  # wrong number of answers

    new = teacher.start_quiz(session, "new")
    assert new.attempt == 3


def test_restart_before_any_quiz_writes_one(teacher):
    session = finish_lecture(teacher)
    assert teacher.start_quiz(session, "restart").attempt == 1


def test_topics_can_be_replayed_after_the_lecture(teacher):
    session = finish_lecture(teacher)
    replay = teacher.send_event(session, GoToTopicEvent(topic_index=0))
    assert replay.current_topic == 0
    assert replay.quiz_available  # stays unlocked


def test_submit_without_a_quiz_and_unknown_sessions(teacher):
    session = finish_lecture(teacher)
    with pytest.raises(EventNotAllowed):
        teacher.submit_quiz(session, [])
    with pytest.raises(SessionNotFound):
        teacher.start_quiz("nope")


def test_end_session_deletes_the_quiz(teacher):
    session = finish_lecture(teacher)
    teacher.start_quiz(session)
    teacher.end_session(session)
    assert session not in teacher.quizzes
    with pytest.raises(SessionNotFound):
        teacher.submit_quiz(session, [])


# --- question kinds chosen by the LLM -------------------------------------------


def test_prompt_lets_the_llm_choose_question_kinds_to_suit_the_subject():
    prompt = quiz_prompt(make_state(), [0, 1, 2], avoid=[])
    assert STYLE_GUIDE in prompt
    assert "programming lecture mostly text" in prompt
    assert '"style_note"' in prompt


def test_text_questions_need_a_model_answer():
    good = DraftQuestion(**text_draft(0))
    item = clean_draft(good, 3)
    assert item.kind == "text" and item.options == []
    assert clean_draft(good.model_copy(update={"expected_answer": " "}), 3) is None


def test_code_answers_keep_brackets():
    code = DraftQuestion(**text_draft(0, code=True)).model_copy(update={"expected_answer": "xs[0]"})
    assert clean_draft(code, 3).expected_answer == "xs[0]"


def test_mixed_quiz_keeps_the_llms_kinds_and_note():
    llm, _ = fake_llm(mixed_reply_for)
    record = new_quiz(llm, make_state(), None, random.Random(0))
    assert [item.kind for item in record.items] == ["mcq", "text", "mcq", "text", "mcq"]
    assert record.style_note.startswith("A mix")

    quiz = to_quiz("abc", record, OUTLINE)
    assert quiz.style_note == record.style_note
    assert quiz.questions[1].kind == "text" and quiz.questions[1].options == []
    assert "Requests are sent without waiting" not in json.dumps(quiz.model_dump())  # no model answer leaked
    assert restart_quiz(record).style_note == record.style_note


def mixed_record():
    llm, _ = fake_llm(mixed_reply_for)
    return new_quiz(llm, make_state(), None, random.Random(0))


def test_typed_answers_are_graded_by_the_llm_in_one_call():
    record = mixed_record()
    answers = [item.correct_index if item.kind == "mcq" else None for item in record.items]
    answers[1] = "right: no waiting"
    answers[3] = "  something else  "
    llm, sent = fake_llm(grades_reply_for)

    result = mark_quiz(llm, "abc", record, answers, OUTLINE)

    assert len(sent) == 1  # both typed answers in one call
    assert "Student's answer: something else" in sent[0]  # trimmed
    assert (result.score, result.total) == (4, 5)
    assert result.review[1].correct and result.review[1].feedback == "Feedback 1."
    assert result.review[1].answer_text == "right: no waiting"
    assert result.review[3].expected_answer.startswith("Requests are sent")
    assert not result.review[3].correct


def test_blank_typed_answers_are_wrong_without_asking_the_llm():
    record = mixed_record()
    answers = [item.correct_index if item.kind == "mcq" else "" for item in record.items]
    llm, sent = fake_llm(grades_reply_for)
    result = mark_quiz(llm, "abc", record, answers, OUTLINE)
    assert sent == []
    assert result.score == 3
    assert result.review[1].feedback == "You didn't answer this one."


def test_grading_falls_back_to_key_words_when_the_llm_fails():
    record = mixed_record()
    answers = [item.correct_index if item.kind == "mcq" else None for item in record.items]
    answers[1] = "the requests get sent without waiting"
    answers[3] = "no idea"
    result = mark_quiz(NO_LLM, "abc", record, answers, OUTLINE)
    assert result.review[1].correct and not result.review[3].correct
    assert "Checked automatically" in result.review[1].feedback


def test_keyword_grade():
    item = clean_draft(DraftQuestion(**text_draft(0)), 3)
    assert keyword_grade(item, "Requests are sent, no waiting for each response")[0]
    assert not keyword_grade(item, "Responses")[0]


def test_answers_must_fit_the_question_kinds():
    record = mixed_record()
    ok = [0, "text", 1, None, 3]
    assert answers_problem(record, ok) is None
    assert "Expected 5 answers" in answers_problem(record, ok[:4])
    assert "option number" in answers_problem(record, ["text", "text", 1, None, 3])
    assert "option number" in answers_problem(record, [9, "text", 1, None, 3])
    assert "option number" in answers_problem(record, [True, "text", 1, None, 3])
    assert "must be text" in answers_problem(record, [0, 2, 1, None, 3])


def test_mixed_quiz_through_the_teacher(teacher):
    session = finish_lecture(teacher)
    quiz = teacher.start_quiz(session)
    kinds = [q.kind for q in quiz.questions]
    assert "text" in kinds and "mcq" in kinds
    assert quiz.style_note

    answers = [0 if q.kind == "mcq" else "right answer" for q in quiz.questions]
    result = teacher.submit_quiz(session, answers)
    for review in result.review:
        if review.kind == "text":
            assert review.correct and review.feedback.startswith("Feedback")

    with pytest.raises(EventNotAllowed):
        teacher.submit_quiz(session, ["wrong kind"] * len(quiz.questions))

