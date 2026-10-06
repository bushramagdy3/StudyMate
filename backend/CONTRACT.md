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

**End session** isn't an event: the backend calls `teacher.end_session(session_id)`,
which deletes the session (nothing is saved), and the frontend goes to the homepage.
When the student finishes the last topic, Regina says goodbye with a short summary
and `awaiting` becomes `"nothing"`.

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
  "completed_topics": [],
  "can_raise_hand": true
}
```

- **speech**: send each segment to TTS and play them in order.
- **avatar_state**: `idle`, `speaking`, `listening`, `thinking` or `asking_question`.
- **awaiting**: what the UI should allow next:
  - `continue`: play the speech, then automatically send `{"type": "continue"}`
  - `answer`: show the answer box
  - `question`: hand is raised, show the question box
  - `nothing`: the lecture is finished (after the goodbye)
- **outline**, **current_topic**, **completed_topics**: for the progress sidebar.
- **can_raise_hand**: show the raise-hand button only when this is `true`
  (while the teacher is explaining). `raise_hand` is ignored at other times.

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
```

Errors, and the HTTP status to return for them:

| Exception | Meaning | HTTP |
|---|---|---|
| `SessionNotFound` | wrong `session_id`, or the server restarted | 404 |
| `EventNotAllowed` | event sent at the wrong time; nothing changed | 409 |

Sessions are kept in memory: restarting the server ends them.
