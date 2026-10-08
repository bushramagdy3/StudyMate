# Teacher agent contract

How the PDF extraction, the FastAPI backend and the React frontend talk to the
AI teacher agent. The source of truth is `agent/contract.py`; this page shows the
same thing as JSON.

Conventions: topic indexes start at **0**, slide numbers start at **1**.

## 1. Starting a session

The backend sends the extracted lecture plus the chosen environment:

```json
{
  "environment": "lecture_hall",
  "lecture": [
    { "slide": 1, "text": "HTTP versions: 1.0, 1.1, 2, 3" },
    { "slide": 2, "text": "HTTP/1.1 pipelining ..." }
  ]
}
```

`environment` is one of `lecture_hall` (professor), `study_room` (tutor) or
`cafe` (study friend).

## 2. Student events

Every student action is sent as one event, told apart by `type`.

**The lecture:**

| Event | JSON | When |
|---|---|---|
| continue | `{"type": "continue"}` | **Not a button.** Sent automatically when the `speech` has finished playing, if `awaiting` is `"continue"` |
| answer | `{"type": "answer", "text": "..."}` | Student submits an answer to the teacher's question |
| raise_hand | `{"type": "raise_hand", "segment_index": 2}` | Raise-hand button (only when `can_raise_hand` is true); `segment_index` is the position, from 0, in the `speech` list that was playing |
| question | `{"type": "question", "text": "..."}` | Student submits their question after raising their hand |

**The outline** (on the same page, usable any time during the lecture):

| Event | JSON | When |
|---|---|---|
| go_to_topic | `{"type": "go_to_topic", "topic_index": 0}` | Student clicks a topic's name. A topic left halfway resumes where they left it; a finished topic (or the current one) is explained again the same way; a topic not reached yet is taught |
| repeat | `{"type": "repeat", "topic_index": 0}` | Repeat button on a topic they've been taught (in `completed_topics`, or the `current_topic`, or one left halfway); Regina explains it again, differently |
| summary | `{"type": "summary"}` | "Summary" item at the top of the outline, **private tutor only** (show it when `summary_available` is true). Regina summarises the whole lecture; after it plays, `continue` returns to where the student was |

**End session** isn't an event: the backend calls `teacher.end_session(session_id)`,
which deletes the session (nothing is saved), and the frontend goes to the homepage.
When the student finishes the last topic, Regina says the quiz is next and `awaiting`
becomes `"nothing"`. If the student made any mistakes (even if they got the answer
right on the retry), she names those topics to review. Topics can still be clicked
(and repeated) after that, e.g. to revise before the quiz.

Events sent at the wrong time are rejected (HTTP 409) and change nothing.

## 3. What the agent returns (every turn)

```json
{
  "session_id": "abc123",
  "speech": [
    "Let's consider how HTTP evolved.",
    "HTTP/1.1 introduced pipelining..."
  ],
  "avatar_state": "speaking",
  "awaiting": "continue",
  "outline": [
    { "index": 0, "title": "HTTP Versions", "summary": "..." },
    { "index": 1, "title": "Head-of-Line Blocking", "summary": "..." }
  ],
  "current_topic": 0,
  "current_slide": 1,
  "completed_topics": [],
  "can_raise_hand": true,
  "summary_available": false
}
```

- **speech**: send each segment to TTS and play them in order.
- **avatar_state**: `idle`, `speaking`, `listening`, `thinking` or `asking_question`.
- **awaiting**: what the UI should allow next:
  - `continue`: play the speech, then automatically send `{"type": "continue"}`
  - `answer`: show the answer box
  - `question`: hand is raised, show the question box
  - `nothing`: the lecture is finished (after the goodbye)
- **outline**: the topic list shown next to the lecture.
- **current_topic**: the topic being taught (highlight it in the outline).
- **current_slide**: the PDF slide/page currently being explained. Use it to show
  the matching uploaded PDF slide.
- **completed_topics**: topics the student finished; show them in **green**.
  There is no progress bar and no score.
- **summary_available**: show "Summary" at the top of the outline only when this
  is `true` (private tutor, until the lecture ends).
- **can_raise_hand**: show the raise-hand button only when this is `true`
  (while the teacher is explaining). `raise_hand` is ignored at other times.
- **quiz_available**: `true` once every topic is in `completed_topics`. Until
  then the "Quiz" item at the bottom of the outline is locked.
- **lecture_progress**: 0.0 to 1.0, for the progress bar (shown as a %). Finished
  topics count fully; a topic in progress counts by how much of it was said.
  It only reaches 1.0 once every topic is finished.
- **speech_rate**: play the speech at this speed (`audio.playbackRate`). While
  explaining, Regina paces each topic: 0.9 for deep or brand-new concepts
  (`"slow"`, which also gets more, smaller steps), 1.1 for intuitive or familiar
  ones (`"quick"`, fewer steps), otherwise 1.0. Always 1.0 outside explanations.

## 3b. The mini quiz

5 to 10 questions. It isn't a student event: it has its own two routes and
doesn't change the lecture.

Each question is `"mcq"` (pick one of up to 4 `options`) or `"text"` (type the
answer; `code_answer: true` means the answer is code, so show a monospace box).
**The LLM picks the kind of each question to suit the lecture**: mostly mcq for
fact/concept subjects (e.g. biology), a balance for languages, mostly text for
programming. It explains its choice in `style_note`, shown to the student.

| Route | Body | Returns |
|---|---|---|
| `POST /api/sessions/{id}/quiz` | `{"mode": "new"}` or `{"mode": "restart"}` | a `Quiz` |
| `POST /api/sessions/{id}/quiz/answers` | `{"answers": [0, 2, null, ...]}` | a `QuizResult` |

- **new**: new questions (the replay icon). The first quiz focuses on the topics
  the student got wrong during the lecture (2 questions each, 1 on every other
  topic); later ones focus on the topics missed in the last quiz. No mistakes:
  balanced over all topics. Earlier questions aren't repeated.
- **restart**: the same questions again (the quiz's name). Before any quiz,
  it writes a new one.
- **answers**: one per question, in order: the option index for `"mcq"`, the typed
  text for `"text"`, `null` = blank. Typed answers are graded by the LLM in one
  call (by meaning, not wording); if that fails, by matching key words. So
  submitting can take a few seconds when there are typed answers.

```json
{
  "session_id": "abc123",
  "attempt": 1,
  "focus_topics": [{ "index": 1, "title": "Head-of-Line Blocking", "summary": "..." }],
  "style_note": "Mostly multiple choice: this lecture is about telling concepts apart.",
  "questions": [
    {
      "index": 0,
      "topic_index": 1,
      "topic_title": "Head-of-Line Blocking",
      "kind": "mcq",
      "question": "Why does one slow response delay the others?",
      "options": ["...", "...", "...", "..."],
      "code_answer": false
    },
    {
      "index": 1,
      "topic_index": 2,
      "topic_title": "Multiplexing",
      "kind": "text",
      "question": "In one sentence: what does multiplexing allow?",
      "options": [],
      "code_answer": false
    }
  ]
}
```

The answers aren't in the `Quiz`; they come back in the `QuizResult`:

```json
{
  "session_id": "abc123",
  "score": 3,
  "total": 5,
  "feedback": "Nice work. Focus on Head-of-Line Blocking: ...",
  "topics_to_improve": [{ "index": 1, "title": "Head-of-Line Blocking", "summary": "..." }],
  "review": [
    {
      "index": 0, "topic_index": 1, "kind": "mcq", "question": "...", "options": ["..."],
      "chosen_index": 2, "correct_index": 0, "correct": false,
      "explanation": "Why the correct option is right."
    },
    {
      "index": 1, "topic_index": 2, "kind": "text", "question": "...", "options": [],
      "answer_text": "What the student typed", "expected_answer": "A model answer",
      "correct": true, "feedback": "One line from the grader.",
      "explanation": "Why the model answer is right."
    }
  ]
}
```

409 if the quiz is still locked, if there's no quiz to submit, or if the
answers don't fit the questions (wrong count, text for an mcq, a number for a
text question).

## 4. The agent's Python interface

Create **one** `Teacher` when the server starts and share it between requests
(it holds every session):

```python
from agent.teacher import Teacher, SessionNotFound, EventNotAllowed

teacher = Teacher()  # reads FEATHERLESS_API_KEY / FEATHERLESS_MODEL from backend/.env

teacher.start_session(request: StartSessionRequest) -> TeacherResponse
teacher.send_event(session_id: str, event: StudentEvent) -> TeacherResponse
teacher.get_session(session_id: str) -> TeacherResponse  # current turn again, changes nothing
teacher.end_session(session_id: str) -> None             # "end session" button: deletes it
teacher.start_quiz(session_id: str, mode: str = "new") -> Quiz         # "new" or "restart"
teacher.submit_quiz(session_id: str, answers: list[int | str | None]) -> QuizResult
```

Errors, and the HTTP status to return for them:

| Exception | Meaning | HTTP |
|---|---|---|
| `SessionNotFound` | wrong `session_id`, or the server restarted | 404 |
| `EventNotAllowed` | event (or quiz call) at the wrong time; nothing changed | 409 |

Sessions are kept in memory: restarting the server ends them.
