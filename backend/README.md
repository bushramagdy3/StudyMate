Step 1: Agree on the contract with your team

Before building anything, agree on what goes in and out of your component. Everyone can then work in parallel.

What your agent receives:

The lecture text. Ask the PDF person for it split per slide or page, e.g. [{slide: 1, text: "..."}, ...]. That's more useful than one blob.
The chosen environment: lecture_hall, study_room or cafe.
Student events: start, answer(text), raise_hand, question(text), repeat, go_to_topic(n), continue, end.

What your agent returns after each turn:

speech: the text the teacher says. This goes to TTS.
avatar_state: speaking, asking_question, listening or thinking.
awaiting: what input the UI should allow next, such as nothing, answer, question or continue.
outline plus current_topic plus completed_topics, for the progress sidebar.

Write this down as a short shared document. It's the most important step for working as a team.

Step 2: Learn the LangGraph concepts you'll need

You only need a small part of LangGraph:

State: a typed dictionary that every node reads and updates.
Nodes: Python functions such as "explain", "ask question" and "evaluate answer".
Edges and conditional edges: these decide which node runs next, based on the state.
interrupt() and Command(resume=...): these pause the graph to wait for the student, then continue with their input. This is how you'll wait for answers.
Checkpointer (MemorySaver is fine for a hackathon) plus thread_id: this saves state between API calls. Each lecture session gets its own thread_id.

Spend an hour on the official "human-in-the-loop" tutorial. Your whole flow is built on that pattern.

Step 3: Design the state

List every field the agent needs to remember. Building on the README's list:

Field	Purpose
session_id	Identifies the session (used as the thread_id)
personality	The environment's persona config
lecture_chunks	Raw extracted content
outline	List of topics, each with a title, summary, key points and the source slides it came from
current_topic_index	Which topic is being taught
current_segment_index	Position inside the topic (see Step 6)
topic_segments	The explanation for the current topic, split into segments
mode	explaining, asking, awaiting_answer, answering_hand_raise or ended
pending_question	The question the AI just asked, plus its expected answer
student_input	The student's latest answer or question
completed_topics	Used for the progress display
conversation_history	A short memory so replies stay consistent
student_performance	Optional: correct and incorrect counts per topic, used for the end summary

Expect to revise this table as you go.

Step 4: Define the three personalities

Write one config per environment. Personality should only change how the teacher talks, never the flow:

Professor (lecture hall): formal and structured. Uses phrases like "Let's consider…". Asks fewer but deeper questions.
Tutor (study room): patient and encouraging. Checks understanding often and gives step-by-step hints.
Study friend (café): casual, uses analogies, phrases things as "wait, so basically…". Light humour.

Each config holds a system prompt fragment, a tone description, a question frequency, a voice ID for TTS and an avatar ID. Every LLM call puts this fragment into its prompt.

Step 5: Set up the LLM layer (Featherless AI)
Featherless provides an OpenAI-compatible API, so you can use the openai Python client (or LangChain's ChatOpenAI) with their base URL and your API key.
Pick one capable instruction-following model and test it early.
Write one helper for plain text output and one for structured JSON output. The outline and answer evaluation must come back in a parseable format.
Add robustness: validate the JSON (Pydantic is a good fit), retry once on bad output, and use a sensible fallback if the retry also fails. Open-source models often break JSON, so plan for that.
Step 6: Build the planning node (lecture to outline)

This node runs once at the start.

Send the lecture content to the LLM and ask for an outline of small logical topics. Each topic gets a title, a 1–2 sentence goal, key points and the slide numbers it uses.
Keep topics small, around 5–10 for a typical lecture, so each one takes a few minutes.
If the PDF is too long for the model's context window, summarise slides in batches first, then plan from the summaries.
Ground each topic in its source slides. Later nodes then teach from the actual lecture content instead of the model's general knowledge, which reduces hallucination.
Step 7: Build the explain node, in segments

This design decision makes "raise hand" and "repeat" work.

Don't generate one long monologue per topic. Generate the explanation as 3–5 short segments, each a few sentences.
Send segments to the frontend one at a time, or as a list it plays in order. Track current_segment_index as they're delivered.
Why segments: TTS audio plays on the frontend. When the student raises their hand mid-explanation, the frontend tells you which segment it reached. Resuming "exactly where it stopped" then just means continuing from that segment.
Prompt inputs: personality, topic info, source slide text, topics already covered (so you don't repeat them), and the instruction to write speakable text with no markdown, bullet points or code blocks, since TTS reads everything aloud.
Step 8: Build the question, answer and feedback loop

Write three nodes:

Ask question: after a topic, or every N segments depending on personality, generate a short question. Store the question and its expected answer key in state. Set the avatar to asking_question.
Wait for answer: call interrupt(). The graph pauses here until the API resumes it with the student's typed answer.
Evaluate answer: use a structured LLM call that returns correct, partially_correct or incorrect, plus the misconception if there is one.
Feedback: praise, give a hint and let them try again (allow one retry), or explain the correct answer. Phrase it in the personality's voice. Then route on to the next topic.
Step 9: Handle raise hand (the interruption)
A raise_hand event saves the current position (topic and segment are already in state), sets mode = answering_hand_raise, and interrupts to wait for the typed question.
Answer question node: answer it using the current topic's context plus the lecture content. Keep the answer short. If the question is off-topic, answer briefly and steer back.
Then route back to the explain node at the saved segment index, optionally with a short bridge such as "Okay, back to where we were…".
Step 10: Handle navigation commands

Each command is a small state change followed by routing back to the explain node:

Repeat or explain again: re-explain the current topic or segment differently, using simpler words or a new analogy. Don't replay the same text. Pass the previous explanation into the prompt with "explain this differently".
Go to topic N: set current_topic_index = N, reset the segment index and regenerate the segments.
Continue: move to the next segment or topic.
End: route to a closing node. It generates a short wrap-up: what was covered, which topics the student found hard (from student_performance), and a goodbye in character.
Step 11: Wire the graph together and expose it
Assemble the nodes. Add a router (a conditional edge) that reads the incoming event and mode and decides the next node. This is the central control logic, so keep it simple and readable.
Compile the graph with a checkpointer.
Expose a small Python interface the backend person can call from FastAPI, e.g. start_session(lecture, environment) and send_event(session_id, event). Both return the output format from Step 1.
Each API call runs the graph until its next pause point, then returns. One student action produces one response.
Step 12: Test without the frontend
Build a simple command-line loop: load a sample lecture PDF's text, pick a personality, then type answers, raise_hand, repeat and so on.
Test the tricky paths: a hand raise in the middle of a topic, going back to topic 1 and then continuing, a wrong answer followed by a retry, and ending early.
Run the same lecture with all three personalities and compare the tone.
Tune the prompts. That's where most of your quality comes from.
Step 13: Polish if time allows
Streaming: send the first segment as soon as it's ready to reduce waiting.
Pre-generate the next topic's segments while the student is answering, to hide LLM latency.
Adaptive pacing: if the student keeps getting questions wrong, ask the explain node to slow down and simplify.
