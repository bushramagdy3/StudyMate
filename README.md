# AI Lecture Companion — ForgeHacks 2026

A project for the **ForgeHacks AI + Education** track.

The idea is to turn a normal lecture PDF into an **interactive AI-led lecture**.

The user uploads their lecture slides, chooses a learning environment such as a **lecture hall, private tutoring session, or café with a study friend**, and an AI character teaches the lecture aloud while actively interacting with the student.

## Tech Stack

- **Frontend:** React
- **Backend:** Python + FastAPI
- **AI Workflow:** LangGraph
- **LLM:** Featherless AI
- **Voice:** External Text-to-Speech API
- **Avatar / Environment:** 2D animated avatar + 2D room/background

## How It Works

```text
Upload Lecture PDF
        ↓
Backend extracts lecture content
        ↓
User chooses learning environment
        ↓
Environment determines AI personality
        ↓
AI analyzes the lecture
        ↓
AI creates a topic-based session outline
        ↓
Interactive lecture begins
```

The lecture will **not necessarily follow one slide at a time**. The AI will divide the lecture into small logical topics/concepts and create a teaching flow from them.

Example:

```text
Lecture Outline

1. HTTP Versions
2. HTTP/1.1 Pipelining
3. Head-of-Line Blocking
4. HTTP/2 Multiplexing
5. HTTP/3
```

## LangGraph Workflow

LangGraph will control the state of the lecture and decide what the AI should do next.

The state will keep track of things such as:

```text
- selected learning environment / AI personality
- lecture outline
- current topic
- current position inside the topic
- whether the AI is explaining
- whether the AI is asking a question
- whether the student raised their hand
- the student's current question/answer
- completed topics
```

### Normal Lecture Flow

```text
Explain Topic
      ↓
Ask Student Question
      ↓
Wait for Text Answer
      ↓
Evaluate Answer
      ↓
Give Feedback
      ↓
Continue Lecture
```

Student participation will initially be **text-based only**. The student types answers into a text box instead of using microphone input.

## Raise Hand

During the lecture, the student can **raise their hand** whenever they have a question.

```text
AI is explaining
      ↓
Student raises hand
      ↓
Pause lecture
      ↓
Student types question
      ↓
AI answers
      ↓
Resume exactly where the lecture stopped
```

The LangGraph state allows the AI to remember where it was before answering the interruption.

## Session Outline

The student can always see the current lecture outline and their progress.

They can:

- see which topic is currently being explained
- go back to a previous topic
- use a **repeat / explain again** button if they did not understand something
- continue through the lecture
- end the session whenever they want

## Voice

The LLM generates what the teacher should say as text.

```text
LLM Response
    ↓
External TTS API
    ↓
Audio
    ↓
AI Avatar Speaks
```

We will use a separate Text-to-Speech service rather than building voice generation ourselves.

## Avatar & Environment

The visual experience will stay intentionally lightweight for the hackathon.

The AI will be represented by a **2D animated avatar** with states such as:

```text
Idle
Speaking
Listening
Thinking
Asking a Question
```

The selected learning environment will also be **2D**, for example:

- **Lecture Hall** → Professor personality
- **Private Study Room** → Tutor personality
- **Café** → Study-friend personality

All environments use the same AI system — only the personality, voice, avatar, and visual setting change.

## MVP Goal

**Upload PDF → choose environment → AI plans lecture → AI teaches aloud → student participates → student can raise their hand → AI asks questions → user can repeat topics or end the session.**
