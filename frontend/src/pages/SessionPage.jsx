import { useState } from 'react'
import { MessageBar } from '../components/MessageBar.jsx'
import { SessionOutline } from '../components/SessionOutline.jsx'

export function SessionPage({ environment }) {
  const [activeTopic, setActiveTopic] = useState(0)

  return (
    <main className={`screen session-page ${environment.id}`}>
      <section className="session-stage" aria-label={`${environment.name} session`}>
        <img
          className="session-background"
          src={environment.background}
          alt=""
        />

        <div
          className="pdf-slide-slot"
          aria-label="PDF slide will appear here"
          data-pdf-slide-slot
        />

        <img
          className="session-avatar"
          src={environment.avatar}
          alt=""
        />
      </section>

      <SessionOutline
        activeTopic={activeTopic}
        onSelectTopic={setActiveTopic}
      />

      <MessageBar />
    </main>
  )
}
