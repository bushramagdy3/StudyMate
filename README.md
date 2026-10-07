# StudyMate

**StudyMate turns lecture PDFs into interactive AI-led study sessions.**

Built for the **ForgeHacks 2026 AI + Education Track**, StudyMate aims to help students move beyond memorization by actively explaining concepts, asking questions, giving feedback, tracking weak areas, and keeping the learning experience interactive.

## Why StudyMate?

Lecture slides are usually designed to support a professor's explanation, not replace it. They often contain brief text, diagrams, formulas, and examples that can be difficult to understand alone.

Uploading the slides to a normal AI chatbot can help, but the experience is still very different from attending a real lecture: the AI can lose its place, explanations become disconnected from the slides, and asking questions can interrupt the original flow.

StudyMate was built to make studying a lecture feel more like **actually being taught it**.

---

## What It Does

1. Upload a lecture PDF.
2. StudyMate analyzes each slide, including important diagrams and visual content.
3. The lecture is reorganized into a logical topic-based outline.
4. Choose one of three learning environments:
   - **Lecture Hall** — Professor Regina
   - **Private Tutor** — one-on-one tutoring
   - **Study Café** — casual study-friend experience
5. Regina teaches each topic aloud while the relevant PDF slide stays synchronized.
6. The AI asks questions during the lesson and evaluates the student's answers.
7. Wrong answers receive hints and another attempt instead of immediately revealing the solution.
8. Students can **raise their hand** during an explanation, ask a question, and resume from the exact point where the lecture stopped.
9. Completed topics can be replayed with a different explanation.
10. Topics the student struggles with are stored so they can be emphasized in the final adaptive quiz.

---

## How It Works

```text
Upload PDF
    ↓
PyMuPDF processes slides
    ↓
Visual slides → Featherless multimodal analysis
    ↓
AI creates topic-based lecture outline
    ↓
LangGraph manages the teaching session
    ↓
Explain → Question → Evaluate → Feedback
    ↓
Track weak topics
    ↓
Adaptive final quiz
```

The **LangGraph** agent keeps track of the current topic, current slide, explanation position, completed topics, questions, answers, conversation context, and topics the student needs to improve.

This allows StudyMate to behave like one continuous lesson instead of a sequence of disconnected chatbot messages.

---

## Key Features

- AI-generated lecture outline
- Multimodal understanding of diagrams and visual slides
- Three different tutor personalities
- Spoken AI explanations
- Synchronized PDF slides
- Live subtitles
- Questions during explanations
- AI answer evaluation
- Hints and retries
- Raise-hand interruptions
- Exact explanation resume
- Topic replay with a new explanation
- Weak-topic tracking
- Adaptive final quiz

---

## Tech Stack

**Frontend:** React, JavaScript, HTML, CSS, Vite, PDF.js

**Backend:** Python, FastAPI, Pydantic, PyMuPDF, HTTPX

**AI Workflow:** LangGraph

**LLM & Multimodal AI:** Featherless AI

**Text-to-Speech:** Fish Audio

---

# Run Locally

## 1. Clone the repository

```bash
git clone https://github.com/bushramagdy3/StudyMate.git
cd StudyMate
```

## 2. Backend

```bash
cd backend
python -m venv venv
```

Activate the environment.

### Windows

```bash
venv\Scripts\activate
```

### macOS / Linux

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create:

```text
backend/.env
```

Add these two API keys:

```env
FEATHERLESS_API_KEY=your_featherless_api_key
FISH_AUDIO_API_KEY=your_fish_audio_api_key
```

Start the backend:

```bash
uvicorn main:app --reload
```

The backend runs at:

```text
http://127.0.0.1:8000
```

---

## 3. Frontend

Open another terminal:

```bash
cd frontend
npm install
npm run dev
```

Then open the local URL shown by Vite, usually:

```text
http://localhost:5173
```

---

## API Notice

StudyMate depends on external AI APIs, so API availability depends on the providers and the API keys being used.

The project currently uses Fish Audio's:

```text
s2.1-pro-free
```

Fish Audio currently states that free access to this model is available through **November 30, 2026**. After that date, the free model may be changed, extended, or become unavailable, which could cause StudyMate's text-to-speech feature to stop working until the integration is updated.

Featherless AI also requires a valid API key and available API credits.

---

## Project Structure

```text
StudyMate/
├── backend/
│   ├── agent/          # LangGraph teaching workflow
│   ├── main.py         # FastAPI routes, PDF processing and TTS
│   └── requirements.txt
│
├── frontend/
│   ├── public/         # Pregenerated audio
│   ├── src/
│   │   ├── assets/
│   │   ├── components/
│   │   ├── pages/
│   │   └── utils/
│   └── package.json
│
└── README.md
```

---

## ForgeHacks 2026

StudyMate was built around the Education Track challenge:

> **Build an AI-powered solution that helps learners move beyond memorization, understand concepts, make connections, and apply what they learn.**

Instead of making another AI that simply answers questions, StudyMate tries to create an AI that **actually teaches, interacts, remembers, and adapts to the learner.**