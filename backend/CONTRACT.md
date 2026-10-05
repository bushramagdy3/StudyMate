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

Every student action is sent as one event, told apart by `type`:

| Event | JSON | When |
|---|---|---|
| answer | `{"type": "answer", "text": "..."}` | Student submits an answer to the teacher's question |
| raise_hand | `{"type": "raise_hand", "segment_index": 2}` | Student raises their hand; `segment_index` is the speech segment that was playing |
| question | `{"type": "question", "text": "..."}` | Student submits their question after raising their hand |
| repeat | `{"type": "repeat"}` | "Explain again" button |
| go_to_topic | `{"type": "go_to_topic", "topic_index": 0}` | Student clicks a topic in the outline |
| continue | `{"type": "continue"}` | The current speech has finished playing |
| end | `{"type": "end"}` | Student ends the session |

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
  "completed_topics": []
}
```

- **speech**: send each segment to TTS and play them in order.
- **avatar_state**: `idle`, `speaking`, `listening`, `thinking` or `asking_question`.
- **awaiting**: what the UI should allow next:
  - `continue`: play the speech, then send `{"type": "continue"}`
  - `answer`: show the answer box
  - `question`: hand is raised, show the question box
  - `nothing`: the session is over
- **outline**, **current_topic**, **completed_topics**: for the progress sidebar.

## 4. The agent's Python interface

The FastAPI routes call exactly two methods:

```python
agent.start_session(request: StartSessionRequest) -> TeacherResponse
agent.send_event(session_id: str, event: StudentEvent) -> TeacherResponse
```
