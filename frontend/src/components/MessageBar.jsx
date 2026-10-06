import { useState } from 'react'
import handIcon from '../assets/generated-icons/hand-transparent.png'

export function MessageBar() {
  const [isHandRaised, setIsHandRaised] = useState(false)

  return (
    <section className="message-bar" aria-label="Ask a question">
      <input
        className="message-input"
        placeholder="Type your message..."
        type="text"
      />

      <button className="message-send" type="button">
        Send
      </button>

      <button
        className={isHandRaised ? 'raise-hand raised' : 'raise-hand'}
        type="button"
        aria-pressed={isHandRaised}
        onClick={() => setIsHandRaised(!isHandRaised)}
      >
        <img src={handIcon} alt="" />
        <span>Raise Hand</span>
      </button>
    </section>
  )
}
