import { useEffect, useState } from 'react'
import { MessageBar } from '../components/MessageBar.jsx'
import { SessionOutline } from '../components/SessionOutline.jsx'
import { sessionState } from '../data/sessionState.js'

async function playTutorSpeech(text) {
  const speechText = Array.isArray(text)
    ? text.join(' ')
    : text

  if (!speechText) return

  const response = await fetch("http://127.0.0.1:8000/api/tutor-speech", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text: speechText
    })
  })

  if (!response.ok) {
    throw new Error("Could not generate tutor speech")
  }

  const audioBlob = await response.blob()
  const audioUrl = URL.createObjectURL(audioBlob)

  const audio = new Audio(audioUrl)

  audio.onended = () => {
    URL.revokeObjectURL(audioUrl)
  }

  await audio.play()
}

export function SessionPage({ environment }) {
  const [teacherResponse, setTeacherResponse] = useState(sessionState)

  const avatarPosture = teacherResponse.avatar_state || 'idle'

  const avatarImage =
    environment.avatars[avatarPosture] ||
    environment.avatars.idle ||
    environment.avatar

  const currentTopic = teacherResponse.outline.find(
    (topic) => topic.index === teacherResponse.current_topic,
  )

  const [currentSpeech, setCurrentSpeech] = useState(
    "Hello! I'm Regina, your Teacher."
  )

  useEffect(() => {
    if (currentSpeech !== "Hello! I'm Regina, your Teacher.") {
      playTutorSpeech(currentSpeech).catch(console.error)
    }
  }, [currentSpeech])

  useEffect(() => {
    async function temp(){
        setCurrentSpeech(teacherResponse.speech)
    }
    temp();
  }, [teacherResponse.speech])

  function chooseTopic(topicIndex) {
    setTeacherResponse((response) => ({
      ...response,
      avatar_state: 'speaking',
      awaiting: 'continue',
      current_topic: topicIndex,
      speech: [
        `Let's move to ${response.outline[topicIndex]?.title || 'this topic'}.`,
      ],
    }))
  }

  function raiseHand() {
    setTeacherResponse((response) => ({
      ...response,
      avatar_state: 'listening',
      awaiting: 'question',
      speech: ['What would you like to ask?'],
    }))
  }

  function sendMessage(text) {
    setTeacherResponse((response) => {
      const topic =
        response.outline.find(
          (item) => item.index === response.current_topic
        ) ||
        response.outline[0]

      if (response.awaiting === 'answer') {
        return {
          ...response,
          avatar_state: 'speaking',
          awaiting: 'continue',
          speech: [
            `Thanks for answering. We will use that to continue ${topic.title}.`,
          ],
        }
      }

      if (response.awaiting === 'question') {
        return {
          ...response,
          avatar_state: 'speaking',
          awaiting: 'continue',
          speech: [
            `Good question. Here is a short explanation connected to ${topic.title}: ${text}`,
          ],
        }
      }

      return response
    })
  }

  return (
    <main className={`screen session-page ${environment.id}`}>
      <p className="visually-hidden" aria-live="polite">
        {teacherResponse.speech.join(' ')}
      </p>

      <section
        className="session-stage"
        aria-label={`${environment.name} session`}
      >
        <img
          className="session-background"
          src={environment.background}
          alt=""
        />

        <div
          className="pdf-slide-slot"
          aria-label={`PDF slide for ${
            currentTopic?.title || 'the current topic'
          } will appear here`}
          data-pdf-slide-slot
        />

        <img
          className="session-avatar"
          src={avatarImage}
          alt=""
          data-posture={avatarPosture}
        />
      </section>

      <SessionOutline
        completedTopics={teacherResponse.completed_topics}
        currentTopic={teacherResponse.current_topic}
        onSelectTopic={chooseTopic}
        outline={teacherResponse.outline}
      />

      <MessageBar
        awaiting={teacherResponse.awaiting}
        onRaiseHand={raiseHand}
        onSendMessage={sendMessage}
      />
    </main>
  )
}