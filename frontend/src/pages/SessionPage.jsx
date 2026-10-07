import { useEffect, useState } from 'react'
import { MessageBar } from '../components/MessageBar.jsx'
import { PdfSlideViewer } from '../components/PdfSlideViewer.jsx'
import { SessionOutline } from '../components/SessionOutline.jsx'
import { getPregeneratedSpeech } from '../data/pregeneratedSpeech.js'
import { sessionState } from '../data/sessionState.js'
import { playSpeech } from '../utils/speechAudio.js'

function logSpeechError(error) {
  if (error?.name !== 'AbortError') {
    console.error(error)
  }
}

function makeInitialTeacherResponse(environmentId) {
  return {
    ...sessionState,
    speech: [getPregeneratedSpeech(environmentId, 'welcome').text],
  }
}

export function SessionPage({ environment, pdfUrl }) {
  const [teacherResponse, setTeacherResponse] = useState(() =>
    makeInitialTeacherResponse(environment.id),
  )

  const avatarPosture = teacherResponse.avatar_state || 'idle'

  const avatarImage =
    environment.avatars[avatarPosture] ||
    environment.avatars.idle ||
    environment.avatar

  const currentTopic = teacherResponse.outline.find(
    (topic) => topic.index === teacherResponse.current_topic,
  )
  const currentSlide = teacherResponse.current_slide || 1

  useEffect(() => {
    playSpeech(teacherResponse.speech, environment.id).catch(logSpeechError)
  }, [environment.id, teacherResponse.speech])

  function chooseTopic(topicIndex) {
    setTeacherResponse((response) => ({
      ...response,
      avatar_state: 'speaking',
      awaiting: 'continue',
      can_raise_hand: true,
      current_topic: topicIndex,
      current_slide: topicIndex + 1,
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
      can_raise_hand: false,
      speech: [getPregeneratedSpeech(environment.id, 'handRaisePrompt').text],
    }))
  }

  function sendMessage(text) {
    const submittedAwaiting = teacherResponse.awaiting

    setTeacherResponse((response) => {
      return {
        ...response,
        avatar_state: 'thinking',
        awaiting: 'nothing',
        can_raise_hand: false,
        speech: [getPregeneratedSpeech(environment.id, 'thinking').text],
      }
    })

    window.setTimeout(() => {
      setTeacherResponse((response) => {
        const topic =
          response.outline.find(
            (item) => item.index === response.current_topic
          ) ||
          response.outline[0]

        if (submittedAwaiting === 'answer') {
          return {
            ...response,
            avatar_state: 'speaking',
            awaiting: 'continue',
            can_raise_hand: true,
            speech: [
              `Thanks for answering. We will use that to continue ${topic.title}.`,
            ],
          }
        }

        if (submittedAwaiting === 'question') {
          return {
            ...response,
            avatar_state: 'speaking',
            awaiting: 'continue',
            can_raise_hand: true,
            speech: [
              `Good question. Here is a short explanation connected to ${topic.title}: ${text}`,
            ],
          }
        }

        return response
      })
    }, 1200)
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
          aria-label={`PDF slide ${currentSlide} for ${
            currentTopic?.title || 'the current topic'
          }`}
          data-pdf-slide-slot
        >
          <PdfSlideViewer
            pdfUrl={pdfUrl}
            slideNumber={currentSlide}
            topicTitle={currentTopic?.title}
          />
        </div>

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
        canRaiseHand={teacherResponse.can_raise_hand}
        onRaiseHand={raiseHand}
        onSendMessage={sendMessage}
      />
    </main>
  )
}
