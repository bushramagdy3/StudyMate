import { useState } from 'react'
import { AppHeader, PixelButton } from './AppHeader.jsx'
import { environments, topics } from '../data/studyMate.js'
import { mockReply } from '../services/mockService.js'
import handIcon from '../assets/raise-hand-icon.png'
import sendIcon from '../assets/send-icon.png'
import repeatIcon from '../assets/repeat-icon.png'
import documentIcon from '../assets/slide-document.png'
import { SessionArtwork } from './SessionArtwork.jsx'

export function SessionOutline({ currentTopic, completed, onSelect, onRepeat }) {
  return <aside className="session-outline"><h2>Session Outline</h2><ol>{topics.map((topic, index) => <li key={topic} className={`${currentTopic === index + 1 ? 'current' : ''} ${completed.includes(index + 1) ? 'completed' : ''}`}>
    <button className="topic-select" onClick={() => onSelect(index + 1)} aria-current={currentTopic === index + 1 ? 'step' : undefined}><span className="topic-number">{completed.includes(index + 1) ? '✓' : index + 1}</span><span>{topic}</span></button>
    <button className="repeat-button" onClick={() => onRepeat(index + 1)} aria-label={`Repeat ${topic}`}><img src={repeatIcon} alt="" /> <span>Repeat</span></button>
  </li>)}</ol><p className="topic-progress">Topic {currentTopic} of {topics.length}</p></aside>
}

export function SlidePreview({ topic, environment, mode, messages }) {
  const latest = messages[messages.length - 1]
  return <section className="slide-preview" aria-label="Lecture content">
    <div className="slide-card"><img className="slide-icon" src={documentIcon} alt="" /><h2>{mode === 'answering' && latest?.role === 'assistant' ? 'StudyMate says' : topic}</h2><p>{mode === 'paused' ? 'Lecture paused. Ask your question below, then continue when you are ready.' : mode === 'answering' && latest?.role === 'assistant' ? latest.text : `Your ${environment.label.toLowerCase()} guide is presenting this topic.`}</p></div>
  </section>
}

export function SessionInputBar({ mode, onRaiseHand, onResume, onSend }) {
  const [text, setText] = useState('')
  const submit = (event) => { event.preventDefault(); if (!text.trim()) return; onSend(text.trim()); setText('') }
  const placeholder = mode === 'paused' ? 'Type your question...' : 'Type your answer or share a thought...'
  return <form className="session-input-bar" onSubmit={submit}>
    <input aria-label={placeholder} value={text} onChange={(event) => setText(event.target.value)} placeholder={placeholder} />
    {(mode === 'paused' || mode === 'answering') && <PixelButton type="button" onClick={onResume}>Resume</PixelButton>}
    {mode !== 'paused' && mode !== 'answering' && <button type="button" className="raise-hand" onClick={onRaiseHand}><img src={handIcon} alt="" /> Raise Hand</button>}
    <button className="send-button" type="submit" aria-label="Send message"><img src={sendIcon} alt="" /></button>
  </form>
}

export function SessionEndDialog({ onHome, onResume }) {
  return <div className="modal-shield"><section className="end-dialog" role="dialog" aria-modal="true" aria-labelledby="ended-heading"><h2 id="ended-heading">End this session?</h2><p>Your study session will be paused.</p><div><PixelButton onClick={onResume}>Keep Studying</PixelButton><PixelButton kind="primary" onClick={onHome}>Return Home</PixelButton></div></section></div>
}

export function LectureSession({ environmentId, state, navigate }) {
  const config = environments[environmentId]
  const selectTopic = (index) => { state.setCurrentTopic(index); state.setMode('explaining') }
  const repeat = (index) => { state.setCurrentTopic(index); state.setMode('explaining'); state.setMessages((items) => [...items, { role: 'assistant', text: `Let's go over "${topics[index - 1]}" once more.` }]) }
  const send = async (text) => {
    const wasPaused = state.mode === 'paused'
    state.setMessages((items) => [...items, { role: 'student', text }])
    state.setMode('thinking')
    const reply = await mockReply(text, { wasPaused, topic: topics[state.currentTopic - 1], persona: config.persona })
    state.setMessages((items) => [...items, { role: 'assistant', text: reply }])
    state.setMode(wasPaused ? 'answering' : 'explaining')
  }
  const endSession = () => { state.setEnded(true); state.setMode('ended') }
  const finish = () => { state.setEnded(false); navigate('/') }
  const resume = () => { state.setMode('explaining'); state.setCompleted((items) => items.includes(state.currentTopic) ? items : [...items, state.currentTopic]) }
  return <main className={`scene session-scene session-${environmentId}`}>
    <SessionArtwork environmentId={environmentId} />
    <AppHeader session onEnd={endSession} />
    <SessionOutline currentTopic={state.currentTopic} completed={state.completed} onSelect={selectTopic} onRepeat={repeat} />
    <SlidePreview topic={topics[state.currentTopic - 1]} environment={config} mode={state.mode} messages={state.messages} />
    {state.messages.length > 0 && <section className="message-log" aria-live="polite">{state.messages.slice(-3).map((message, index) => <p className={message.role} key={`${index}-${message.text}`}><b>{message.role === 'student' ? 'You' : config.persona}:</b> {message.text}</p>)}</section>}
    {state.mode === 'thinking' && <span className="thinking-status" aria-live="polite">{config.persona} is thinking...</span>}
    <SessionInputBar mode={state.mode} onRaiseHand={() => state.setMode('paused')} onResume={resume} onSend={send} />
    {state.ended && <SessionEndDialog onHome={finish} onResume={() => { state.setEnded(false); state.setMode('explaining') }} />}
  </main>
}
