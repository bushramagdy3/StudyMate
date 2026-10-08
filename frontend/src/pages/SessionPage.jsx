import { useCallback, useEffect, useRef, useState } from 'react'
import { sendSessionEvent } from '../api/studyMateApi.js'
import { MessageBar } from '../components/MessageBar.jsx'
import { PdfSlideViewer } from '../components/PdfSlideViewer.jsx'
import { SessionOutline } from '../components/SessionOutline.jsx'
import { TopicSummaryPopup } from '../components/TopicSummaryPopup.jsx'
import { playSpeech, playThinkingSpeech, stopSpeech } from '../utils/speechAudio.js'

function statusForAutomaticContinue(phase) {
  if (phase === 'explaining') return 'Preparing a question…'
  if (phase === 'answering_student') return 'Returning to where we left off…'
  if (phase === 'feedback') return 'Continuing the lesson…'
  if (phase === 'summarizing') return 'Returning to the lesson…'
  if (phase === 'intro') return 'Getting the session ready…'
  return 'Thinking…'
}

function statusForCurrentPhase(phase) {
  if (phase === 'awaiting_answer') return 'Question time'
  if (phase === 'awaiting_student_question') return 'Ask your question'
  if (phase === 'answering_student') return 'Answering your question'
  return ''
}

function postureAfterSpeech(awaiting) {
  if (awaiting === 'answer' || awaiting === 'question') {
    return 'listening'
  }

  if (awaiting === 'continue') {
    return 'thinking'
  }

  return 'idle'
}

export function SessionPage({
  environment,
  initialTeacherResponse,
  pdfUrl,
  onTeacherResponseChange,
  onError,
}) {
  const [teacherResponse, setTeacherResponse] = useState(initialTeacherResponse)
  const [isPending, setIsPending] = useState(false)
  const [pendingAction, setPendingAction] = useState(null)
  const [subtitle, setSubtitle] = useState('')
  const [isAudioPending, setIsAudioPending] = useState(false)
  const [avatarPosture, setAvatarPosture] = useState('idle')
  const [isLectureSummaryOpen, setIsLectureSummaryOpen] = useState(false)
  const [displayedSlide, setDisplayedSlide] = useState(
    initialTeacherResponse.current_slide || 1,
  )
  const playingSegment = useRef(0)
  const actionToken = useRef(0)
  const eventRequests = useRef(new Set())
  const isBusy = isPending || isAudioPending

  const avatarImage =
    environment.avatars[avatarPosture] ||
    environment.avatars.idle ||
    environment.avatar

  const currentTopic = teacherResponse.outline.find(
    (topic) => topic.index === teacherResponse.current_topic,
  )
  const currentSlide = displayedSlide
  const introIsPlaying =
    teacherResponse.current_topic === null &&
    teacherResponse.awaiting === 'continue'
  const stageStatus =
    pendingAction?.label ||
    (isAudioPending ? 'Preparing Regina’s response…' : statusForCurrentPhase(teacherResponse.phase))

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

  const handleSpeechError = useCallback((error) => {
    if (error?.name === 'AbortError') {
      return
    }

    setSubtitle('')
    setIsAudioPending(false)
    setAvatarPosture('idle')
    onError?.(error, 'Could not play Regina’s response')
  }, [onError])

  const sendEvent = useCallback(async (event, options = {}) => {
    const token = actionToken.current + 1
    actionToken.current = token

    // Never leave old audio or an older request running while the student
    // starts a new action. Otherwise two responses can race and corrupt the UI.
    stopSpeech()
    setSubtitle('')
    setIsAudioPending(false)
    setAvatarPosture('thinking')
    eventRequests.current.forEach((request) => request.abort())
    eventRequests.current.clear()

    const controller = new AbortController()
    eventRequests.current.add(controller)
    setIsPending(true)
    setPendingAction({
      label: options.status || 'Thinking…',
      topicIndex: options.topicIndex ?? null,
    })

    if (options.playThinking) {
      playThinkingSpeech(environment.id, {
        onStart: () => {
          if (token === actionToken.current) {
            setAvatarPosture('speaking')
          }
        },
        onEnd: () => {
          if (token === actionToken.current) {
            setAvatarPosture('thinking')
          }
        },
        onSegment: (_index, text) => {
          if (token === actionToken.current) {
            setSubtitle(text)
          }
        },
      }).catch(handleSpeechError)
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
        setAvatarPosture('idle')
        onError?.(error, 'Could not continue the session')
      }
    } finally {
      eventRequests.current.delete(controller)

      if (token === actionToken.current) {
        setIsPending(false)
        setPendingAction(null)
      }
    }
  }, [
    applyTeacherResponse,
    environment.id,
    handleSpeechError,
    onError,
    teacherResponse.session_id,
  ])

  useEffect(() => {
    const token = actionToken.current

    playSpeech(teacherResponse.speech, environment.id, {
      onWaiting: () => {
        if (token === actionToken.current) {
          setIsAudioPending(true)
          setSubtitle('')
          setAvatarPosture('thinking')
        }
      },
      onStart: () => {
        if (token === actionToken.current) {
          setIsAudioPending(false)
          setAvatarPosture(
            teacherResponse.avatar_state === 'asking_question'
              ? 'asking_question'
              : 'speaking',
          )
        }
      },
      onSegment: (index, text) => {
        if (token === actionToken.current) {
          playingSegment.current = index
          const nextSlide = teacherResponse.speech_slides?.[index]
          if (nextSlide) {
            setDisplayedSlide(nextSlide)
          }
          setSubtitle(text)
        }
      },
    })
      .then(() => {
        if (token === actionToken.current) {
          setSubtitle('')
          setIsAudioPending(false)
          setAvatarPosture(postureAfterSpeech(teacherResponse.awaiting))
        }

        if (
          token === actionToken.current &&
          teacherResponse.awaiting === 'continue'
        ) {
          return sendEvent(
            { type: 'continue' },
            {
              status: statusForAutomaticContinue(teacherResponse.phase),
              topicIndex: teacherResponse.current_topic,
            },
          )
        }

        return null
      })
      .catch(handleSpeechError)
  }, [
    environment.id,
    sendEvent,
    teacherResponse.awaiting,
    teacherResponse.current_topic,
    teacherResponse.phase,
    teacherResponse.speech,
    teacherResponse.speech_slides,
    teacherResponse.avatar_state,
    handleSpeechError,
  ])

  function chooseTopic(topicIndex) {
    if (isBusy) {
      return
    }

    const topic = teacherResponse.outline.find((item) => item.index === topicIndex)
    const isCompleted = teacherResponse.completed_topics.includes(topicIndex)
    const type = isCompleted ? 'repeat' : 'go_to_topic'
    const topicName = topic?.title || 'this topic'

    sendEvent(
      { type, topic_index: topicIndex },
      {
        status: isCompleted
          ? `Preparing a fresh explanation of ${topicName}…`
          : `Preparing ${topicName}…`,
        topicIndex,
      },
    )
  }

  function raiseHand() {
    if (isBusy) {
      return
    }

    sendEvent(
      { type: 'raise_hand', segment_index: playingSegment.current },
      {
        status: 'Pausing the lesson…',
        topicIndex: teacherResponse.current_topic,
      },
    )
  }

  function sendMessage(text) {
    if (isBusy) {
      return
    }

    const isAnswer = teacherResponse.awaiting === 'answer'
    const eventType = isAnswer ? 'answer' : 'question'
    sendEvent(
      { type: eventType, text },
      {
        playThinking: true,
        status: isAnswer
          ? 'Checking your answer…'
          : 'Thinking about your question…',
        topicIndex: teacherResponse.current_topic,
      },
    )
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
            onError={onError}
          />
        </div>

        <img
          className="session-avatar"
          src={avatarImage}
          alt=""
          data-posture={avatarPosture}
        />

        {stageStatus && (
          <div
            className={isBusy ? 'session-flow-status thinking' : 'session-flow-status'}
            role="status"
            aria-live="polite"
          >
            {isBusy && <span className="session-flow-spinner" aria-hidden="true" />}
            <span>{stageStatus}</span>
          </div>
        )}

        {subtitle && (
          // key: each new subtitle is a new element, so it pops in like the panels.
          <p key={subtitle} className="session-subtitles">
            {subtitle}
          </p>
        )}
      </section>

      <SessionOutline
        completedTopics={teacherResponse.completed_topics}
        currentTopic={teacherResponse.current_topic}
        disabled={isBusy || introIsPlaying}
        onOpenLectureSummary={() => setIsLectureSummaryOpen(true)}
        onSelectTopic={chooseTopic}
        outline={teacherResponse.outline}
        pendingTopic={pendingAction?.topicIndex ?? null}
        showLectureSummary={environment.id === 'private-tutor'}
      />

      <MessageBar
        awaiting={teacherResponse.awaiting}
        canRaiseHand={teacherResponse.can_raise_hand}
        disabled={isBusy}
        onRaiseHand={raiseHand}
        onSendMessage={sendMessage}
      />

      <TopicSummaryPopup
        topic={
          isLectureSummaryOpen
            ? {
                title: 'Lecture summary',
                summary: teacherResponse.lecture_summary,
              }
            : null
        }
        onClose={() => setIsLectureSummaryOpen(false)}
      />
    </main>
  )
}
