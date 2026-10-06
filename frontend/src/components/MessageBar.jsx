import { useState } from 'react'
import handIcon from '../assets/generated-icons/hand-transparent.png'

const placeholders = {
  answer: 'Type your answer...',
  continue: 'Type your question or share a thought...',
  nothing: 'Session ended.',
  question: 'Type your question...',
}

export function MessageBar({ awaiting, onRaiseHand, onSendMessage }) {
  const [message, setMessage] = useState('')
  const canSend = ['answer', 'question'].includes(awaiting) && Boolean(message.trim())
  const canRaiseHand = awaiting === 'continue'
  const isHandRaised = awaiting === 'question'

  function sendMessage() {
    const text = message.trim()

    if (!text) {
      return
    }

    onSendMessage(text)
    setMessage('')
  }

  return (
    <section className="message-bar" aria-label="Ask a question">
      <input
        className="message-input"
        disabled={awaiting === 'continue' || awaiting === 'nothing'}
        onChange={(event) => setMessage(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && canSend) {
            sendMessage()
          }
        }}
        placeholder={placeholders[awaiting] || placeholders.continue}
        type="text"
        value={message}
      />

      <button
        className="message-send"
        disabled={!canSend}
        type="button"
        onClick={sendMessage}
      >
        Send
      </button>

      <button
        className={isHandRaised ? 'raise-hand raised' : 'raise-hand'}
        disabled={!canRaiseHand && !isHandRaised}
        type="button"
        aria-pressed={isHandRaised}
        onClick={onRaiseHand}
      >
        <img src={handIcon} alt="" />
        <span>Raise Hand</span>
      </button>
    </section>
  )
}
