# StudyMate

**Your lecture slides, brought to life.** StudyMate transforms lecture PDFs into interactive, voice-led lessons that explain, listen, question, and adapt, so studying independently feels like being taught, not managing a chatbot.

## The Problem

Lecture slides are made to accompany a professor, not replace one. When you miss class, or simply want to study at home, diagrams, formulas, and scattered bullet points can leave you without the explanations that connect them.

The usual workaround is hunting through YouTube videos that rarely match the *entire* lecture, or uploading the slides to ChatGPT or Claude. Videos force students to piece concepts together across sources; chatbots often return dense paragraphs and put the burden on students to keep prompting, manage the lesson's pace, and recover the original thread after asking questions.

**StudyMate changes the experience from asking an AI for explanations to actually attending an AI-led lesson built around your own slides.**

## Why StudyMate?

**A lecture is more than an explanation. It's a continuous, interactive experience.**

Traditional lecture slides are built around a professor's presence. Without that professor, students face disconnected diagrams, brief bullet points, and concepts that are difficult to understand independently.

Searching YouTube means jumping between videos that rarely match the exact lecture. Uploading slides to an AI chatbot may generate explanations, but **the student still has to become the instructor**—deciding what comes next, asking for clarification, requesting questions, and repeatedly guiding the AI back to the lecture.

**StudyMate reverses that relationship.**

Instead of waiting for instructions, its stateful AI agent takes responsibility for the lesson. It teaches concepts in sequence, synchronizes explanations with the relevant slides, asks mandatory understanding-check questions, evaluates answers, and provides hints before moving forward.

Students can raise their hand, ask about an earlier concept, and return to the interrupted explanation without losing their place. The agent remembers the lecture's progress, current slide, questions, and areas of difficulty throughout the session.

**It's not chat with your PDF. It's your lecture, brought to life—with a teacher that guides, challenges, and adapts to you.**

## See StudyMate in Action

### Home

<p align="center"><a href="screenshots/homepage.png"><img src="screenshots/homepage.png" alt="StudyMate home page" width="94%"></a></p>

### From PDF to Classroom

| Upload your lecture | Choose your learning environment |
|:---:|:---:|
| <a href="screenshots/uploadpage.png"><img src="screenshots/uploadpage.png" alt="Upload a lecture PDF" width="100%"></a> | <a href="screenshots/chooseenviromentpage.png"><img src="screenshots/chooseenviromentpage.png" alt="Select a teaching environment" width="100%"></a> |

### Three Ways to Learn

| Lecture Hall | Private Tutor | Study Café |
|:---:|:---:|:---:|
| <a href="screenshots/lecturehallpage.png"><img src="screenshots/lecturehallpage.png" alt="Lecture Hall with professor avatar and lecture slides" width="100%"></a> | <a href="screenshots/privatetutorpage.png"><img src="screenshots/privatetutorpage.png" alt="Private Tutor session" width="100%"></a> | <a href="screenshots/cafepage.png"><img src="screenshots/cafepage.png" alt="Study Café session" width="100%"></a> |

*Click a screenshot to view it at full resolution.*

## What StudyMate Does

- **Reads the actual lecture.** Extracts text and uses multimodal AI to interpret diagrams, tables, equations, and image-heavy slides.
- **Plans before teaching.** Turns the PDF into an ordered topic outline, with explanations tied to the source slides.
- **Teaches out loud.** Combines expressive character personalities, Fish Audio speech, synchronized PDF slides, and live subtitles.
- **Checks real understanding.** Automatically asks conceptual questions, evaluates answers by meaning, and offers hints and retries before revealing solutions.
- **Lets students interrupt naturally.** Raise a hand, ask a typed or recorded question, and return to the lesson without losing your place; pause/resume speech and replay a topic with a different explanation.
- **Targets weak spots.** After the lecture, an adaptive quiz mixes multiple-choice and written-response questions suited to the subject. Mistakes made in the lesson receive extra attention; a new quiz can focus on topics missed in the previous attempt.
- **Offers different learning experiences.** Lecture Hall for structured instruction, Private Tutor for patient step-by-step coaching and summaries, and Study Café for a friendly, conversational approach.

## How It Works

1. **PDF understanding:** FastAPI and PyMuPDF extract slide text; visual-heavy pages are rendered and interpreted using Featherless AI.
2. **Lesson planning:** AI creates slide-grounded topics, explanations, and a concise revision summary.
3. **Agentic teaching:** LangGraph coordinates explanation, understanding checks, grading, hints, hand-raise interruptions, topic navigation, and progress, with checkpointed state maintained during the session.
4. **Multimodal classroom:** React and PDF.js synchronize slides and animations with generated audio from Fish Audio. Optional Groq Whisper transcription converts voice input into editable text.
5. **Adaptive practice:** Session mistakes inform a final quiz. The quiz engine selects topic coverage and question formats, grades responses, and can generate another quiz focused on previously missed topics.

### Agent Workflow Diagram

<!-- TODO: Add the final agent workflow image to docs/agent-workflow.png, then replace the placeholder below with:
![StudyMate agent workflow](docs/agent-workflow.png)
-->

> **Workflow illustration coming soon.** A detailed diagram of the LangGraph teaching agent and its state transitions will appear here.

### Technical Stack

| Layer | Technologies |
|---|---|
| Frontend | React, JavaScript, HTML, CSS, Vite, PDF.js |
| Backend | Python, FastAPI, Pydantic, HTTPX, PyMuPDF |
| AI orchestration | LangGraph, stateful session checkpointing |
| LLM and multimodal interpretation | Featherless AI |
| Speech synthesis | Fish Audio |
| Optional voice transcription | Groq Whisper |

**Not just a PDF chatbot:** StudyMate combines visual document interpretation, structured lesson planning, explicit agent states, interruption-aware playback, and weakness-driven assessment into one continuous study session.

## Demo Video

<!-- TODO: Replace the line below with a public YouTube or Vimeo link once the demo is published. Example:
[▶ Watch the StudyMate demo](https://youtu.be/YOUR_VIDEO_ID)
-->

*Public demo video coming soon.*

## Run Locally

**Prerequisites:** Python 3, Node.js/npm, and API keys for Featherless AI and Fish Audio. Groq is optional for voice input.

### 1. Clone the repository

```bash
git clone https://github.com/bushramagdy3/StudyMate.git
cd StudyMate
```

### 2. Start the backend

```bash
cd backend
python -m venv venv
```

Activate your virtual environment:

- Windows: `venv\Scripts\activate`
- macOS/Linux: `source venv/bin/activate`

Install dependencies:

```bash
pip install -r requirements.txt
```

Create `backend/.env`:

```env
FEATHERLESS_API_KEY=your_featherless_api_key
FISH_AUDIO_API_KEY=your_fish_audio_api_key
# Optional: required only for voice transcription
GROQ_STT_API_KEY=your_groq_api_key
```

Run the API from `backend/`:

```bash
uvicorn main:app --reload
```

### 3. Start the frontend

From the project root, open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL printed by Vite (usually `http://localhost:5173`). By default, the frontend connects to `http://127.0.0.1:8000`; use `VITE_API_BASE_URL` if your backend runs elsewhere.

### API Availability

StudyMate needs valid Featherless AI and Fish Audio credentials. The Fish Audio integration currently targets the `s2.1-pro-free` model; free access is advertised through **November 30, 2026** and may change afterward. Groq transcription requires an additional API key, but text input works without it. Do not commit `.env` or API secrets to GitHub.

### What's Next

**A great professor doesn't forget what happened in the previous lecture. Why should an AI tutor?**

Our vision is to evolve StudyMate from an interactive lecture experience into a **continuous, personalized learning companion** that remembers a student's entire academic journey.

Students will be able to organize lecture PDFs into courses, allowing their AI tutor to connect new concepts to previous lectures, remember what they've already studied, and build on earlier knowledge instead of starting from scratch every session.

StudyMate will also track academic progress beyond lectures, including quiz grades, incorrect answers, and difficulties with practice assignments, to develop a deeper understanding of each student's strengths and weaknesses.

The agent will support different learning modes, from **teaching lectures to guiding students through worksheets and practice problems**, while maintaining shared learning context across them.

Combined with more customizable voices, characters, personalities, and environments, our goal is to create something closer to a real professor: **one who knows your course, remembers your progress, understands where you struggle, and grows with you throughout your education.**

---

*StudyMate was submitted to the **ForgeHacks 2026 — AI + Education** track.*
