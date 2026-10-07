import { useCallback, useEffect, useRef, useState } from 'react'
import { sendSessionEvent } from '../api/studyMateApi.js'
import { MessageBar } from '../components/MessageBar.jsx'
import { PdfSlideViewer } from '../components/PdfSlideViewer.jsx'
import { SessionOutline } from '../components/SessionOutline.jsx'
import { playSpeech, playThinkingSpeech, stopSpeech } from '../utils/speechAudio.js'

function logSpeechError(error) {
  if (error?.name !== 'AbortError') {
    console.error(error)
  }
}

export function SessionPage({
  environment,
  initialTeacherResponse,
  pdfUrl,
  onTeacherResponseChange,
}) {
  const [teacherResponse, setTeacherResponse] = useState(initialTeacherResponse)
  const actionToken = useRef(0)
  const eventRequests = useRef(new Set())

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
    const requests = eventRequests.current

    return () => {
      actionToken.current += 1
      stopSpeech()

      requests.forEach((controller) => controller.abort())
      requests.clear()
    }
  }, [])

  const applyTeacherResponse = useCallback((response) => {
    setTeacherResponse(response)
    onTeacherResponseChange(response)
  }, [onTeacherResponseChange])

  const sendEvent = useCallback(async (event, options = {}) => {
    const token = actionToken.current + 1
    actionToken.current = token
    const controller = new AbortController()
    eventRequests.current.add(controller)

    if (options.playThinking) {
      playThinkingSpeech(environment.id).catch(logSpeechError)
    }

    try {
      const response = await sendSessionEvent(
        teacherResponse.session_id,
        event,
        controller.signal,
      )

      if (token === actionToken.current) {
        applyTeacherResponse(response)
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        console.error(error)
      }
    } finally {
      eventRequests.current.delete(controller)
    }
  }, [
    applyTeacherResponse,
    environment.id,
    teacherResponse.session_id,
  ])

  useEffect(() => {
    const token = actionToken.current

    playSpeech(teacherResponse.speech, environment.id)
      .then(() => {
        if (
          token === actionToken.current &&
          teacherResponse.awaiting === 'continue'
        ) {
          return sendEvent({ type: 'continue' })
        }

        return null
      })
      .catch(logSpeechError)
  }, [
    environment.id,
    sendEvent,
    teacherResponse.awaiting,
    teacherResponse.speech,
  ])

  function chooseTopic(topicIndex) {
    sendEvent({ type: 'go_to_topic', topic_index: topicIndex }, { playThinking: true })
  }

  function raiseHand() {
    sendEvent({ type: 'raise_hand', segment_index: 0 })
  }

  function sendMessage(text) {
    const eventType = teacherResponse.awaiting === 'answer' ? 'answer' : 'question'
    sendEvent({ type: eventType, text }, { playThinking: true })
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
