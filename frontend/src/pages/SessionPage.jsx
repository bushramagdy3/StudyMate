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
  const [isPending, setIsPending] = useState(false)
  const [requestError, setRequestError] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const playingSegment = useRef(0)
  const actionToken = useRef(0)
  const eventRequests = useRef(new Set())

  const avatarPosture = isPending
    ? 'thinking'
    : teacherResponse.avatar_state || 'idle'

  const avatarImage =
    environment.avatars[avatarPosture] ||
    environment.avatars.idle ||
    environment.avatar

  const currentTopic = teacherResponse.outline.find(
    (topic) => topic.index === teacherResponse.current_topic,
  )
  const currentSlide = teacherResponse.current_slide || 1
  const introIsPlaying =
    teacherResponse.current_topic === null &&
    teacherResponse.awaiting === 'continue'

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

    // Never leave old audio or an older request running while the student
    // starts a new action. Otherwise two responses can race and corrupt the UI.
    stopSpeech()
    eventRequests.current.forEach((request) => request.abort())
    eventRequests.current.clear()

    const controller = new AbortController()
    eventRequests.current.add(controller)
    setRequestError('')
    setIsPending(true)

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
      if (error.name !== 'AbortError' && token === actionToken.current) {
        console.error(error)
        setRequestError(error.message || 'Could not continue the session.')
      }
    } finally {
      eventRequests.current.delete(controller)

      if (token === actionToken.current) {
        setIsPending(false)
      }
    }
  }, [
    applyTeacherResponse,
    environment.id,
    teacherResponse.session_id,
  ])

  useEffect(() => {
    const token = actionToken.current

    playSpeech(teacherResponse.speech, environment.id, (index, text) => {
      playingSegment.current = index
      setSubtitle(text)
    })
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
    if (isPending) {
      return
    }

    const isCompleted = teacherResponse.completed_topics.includes(topicIndex)
    const type = isCompleted ? 'repeat' : 'go_to_topic'

    sendEvent(
      { type, topic_index: topicIndex },
      { playThinking: true },
    )
  }

  function raiseHand() {
    if (isPending) {
      return
    }

    sendEvent({ type: 'raise_hand', segment_index: playingSegment.current })
  }

  function sendMessage(text) {
    if (isPending) {
      return
    }

    const eventType = teacherResponse.awaiting === 'answer' ? 'answer' : 'question'
    sendEvent({ type: eventType, text }, { playThinking: true })
  }

  return (
    <main className={`screen session-page ${environment.id}`}>
      <p className="visually-hidden" aria-live="polite">
        {teacherResponse.speech.join(' ')}
      </p>

      {requestError && (
        <p className="session-request-error" role="alert">
          {requestError}
        </p>
      )}

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

        {subtitle && !isPending && (
          // key: each new subtitle is a new element, so it pops in like the panels.
          <p key={subtitle} className="session-subtitles">
            {subtitle}
          </p>
        )}
      </section>

      <SessionOutline
        completedTopics={teacherResponse.completed_topics}
        currentTopic={teacherResponse.current_topic}
        disabled={isPending || introIsPlaying}
        onSelectTopic={chooseTopic}
        outline={teacherResponse.outline}
      />

      <MessageBar
        awaiting={teacherResponse.awaiting}
        canRaiseHand={teacherResponse.can_raise_hand}
        disabled={isPending}
        onRaiseHand={raiseHand}
        onSendMessage={sendMessage}
      />
    </main>
  )
}
