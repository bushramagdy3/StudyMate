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

**During the lecture:**

| Event | JSON | When |
|---|---|---|
| continue | `{"type": "continue"}` | **Not a button.** Sent automatically when the `speech` has finished playing, if `awaiting` is `"continue"` |
| answer | `{"type": "answer", "text": "..."}` | Student submits an answer to the teacher's question |
| raise_hand | `{"type": "raise_hand", "segment_index": 2}` | Raise-hand button (only when `can_raise_hand` is true); `segment_index` is the position, from 0, in the `speech` list that was playing |
| question | `{"type": "question", "text": "..."}` | Student submits their question after raising their hand |
| back | `{"type": "back", "segment_index": 1}` | Back button: leaves for the outline page and saves the student's place; `segment_index` as for raise_hand |

**On the outline page** (when `awaiting` is `"outline"`):

| Event | JSON | When |
|---|---|---|
| go_to_topic | `{"type": "go_to_topic", "topic_index": 0}` | Student picks a topic. The topic in progress resumes exactly where they left; any other topic starts from its beginning |
| repeat | `{"type": "repeat", "topic_index": 0}` | "Explain again" for a topic in `completed_topics` or the `current_topic`; Regina explains it differently |
| end | `{"type": "end"}` | Optional: end the session now with the goodbye summary. The lecture also ends on its own after the last topic |

Events sent at the wrong time are ignored.

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
  - `outline`: lecture paused, show the outline page
  - `nothing`: the session is over
- **outline**, **current_topic**, **completed_topics**: for the progress sidebar.
- **can_raise_hand**: show the raise-hand button only when this is `true`
  (while the teacher is explaining). `raise_hand` is ignored at other times.

## 4. The agent's Python interface

The FastAPI routes call exactly two methods:

```python
agent.start_session(request: StartSessionRequest) -> TeacherResponse
agent.send_event(session_id: str, event: StudentEvent) -> TeacherResponse
```
