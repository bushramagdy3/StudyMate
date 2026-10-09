import { useCallback, useEffect, useRef, useState } from 'react'
import {
  sendSessionEvent,
  startQuiz,
  submitQuiz,
  transcribeAudio,
} from '../api/studyMateApi.js'
import { MessageBar } from '../components/MessageBar.jsx'
import { PdfSlideViewer } from '../components/PdfSlideViewer.jsx'
import { QuizPopup } from '../components/QuizPopup.jsx'
import { SessionOutline } from '../components/SessionOutline.jsx'
import { TopicSummaryPopup } from '../components/TopicSummaryPopup.jsx'
import loadingIcon from '../assets/generated-icons/outline-loading.gif'
import {
  pauseSpeech,
  playSpeech,
  playThinkingSpeech,
  resumeSpeech,
  stopSpeech,
  textForSubtitle,
} from '../utils/speechAudio.js'

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

function PauseIcon({ paused }) {
  return (
    <svg className="speech-pause-icon" viewBox="0 0 24 24" aria-hidden="true" shapeRendering="crispEdges">
      {paused ? (
        <path d="M7 4h3v2h2v2h2v2h2v4h-2v2h-2v2h-2v2H7z" fill="currentColor" />
      ) : (
        <path d="M6 5h4v14H6zM14 5h4v14h-4z" fill="currentColor" />
      )}
    </svg>
  )
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
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [voiceUnavailable, setVoiceUnavailable] = useState(false)
  const [speechRetryKey, setSpeechRetryKey] = useState(0)
  const [avatarPosture, setAvatarPosture] = useState('idle')
  // Regina's speech is playing (explaining, asking or answering): show the pause button.
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  // The posture to go back to when the speech is resumed.
  const speakingPosture = useRef('speaking')
  const [isLectureSummaryOpen, setIsLectureSummaryOpen] = useState(false)
  // The mini quiz: the questions, the marked result, and which view is showing
  // ('loading', 'taking', 'submitting', 'results', 'error'; null = closed).
  const [quiz, setQuiz] = useState(null)
  const [quizProgress, setQuizProgress] = useState(null)
  const [quizResult, setQuizResult] = useState(null)
  const [quizStatus, setQuizStatus] = useState(null)
  const [quizError, setQuizError] = useState('')
  const [quizErrorAction, setQuizErrorAction] = useState('retry')
  const quizRequest = useRef(null)
  // What to do on "Try again": the request that failed.
  const failedQuizAction = useRef(null)
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
    (isPaused ? 'Paused' : '') ||
    pendingAction?.label ||
    (isAudioPending ? 'Preparing Regina’s response…' : statusForCurrentPhase(teacherResponse.phase))

  useEffect(() => {
    const requests = eventRequests.current

    return () => {
      actionToken.current += 1
      stopSpeech()

      requests.forEach((controller) => controller.abort())
      requests.clear()
      quizRequest.current?.abort()
    }
  }, [])

  const applyTeacherResponse = useCallback((response) => {
    setTeacherResponse(response)
    onTeacherResponseChange(response)
  }, [onTeacherResponseChange])

  const handleSpeechError = useCallback((error, onRetry) => {
    if (error?.name === 'AbortError') {
      return
    }

    setSubtitle('')
    setIsAudioPending(false)
    setAvatarPosture('idle')
    onError?.(error, 'Could not play Regina’s response', onRetry)
  }, [onError])

  const sendEvent = useCallback(async (event, options = {}) => {
    const token = actionToken.current + 1
    actionToken.current = token

    // Never leave old audio or an older request running while the student
    // starts a new action. Otherwise two responses can race and corrupt the UI.
    stopSpeech()
    setIsSpeaking(false)
    setIsPaused(false)
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
        onError?.(error, 'Could not continue the session', () => sendEvent(event, options))
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
      rate: teacherResponse.speech_rate,
      onWaiting: () => {
        if (token === actionToken.current) {
          setIsAudioPending(true)
          setSubtitle('')
          setAvatarPosture('thinking')
        }
      },
      onStart: () => {
        if (token === actionToken.current) {
          const posture =
            teacherResponse.avatar_state === 'asking_question'
              ? 'asking_question'
              : 'speaking'
          speakingPosture.current = posture
          setIsAudioPending(false)
          setIsSpeaking(true)
          setAvatarPosture(posture)
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
          // A question stays on screen until it's answered, in case the
          // student missed it while it was being read out.
          setSubtitle(
            teacherResponse.awaiting === 'answer'
              ? textForSubtitle(teacherResponse.speech.join(' '))
              : '',
          )
          setIsAudioPending(false)
          setIsSpeaking(false)
          setIsPaused(false)
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
      .catch((error) => {
        if (token === actionToken.current) {
          setIsSpeaking(false)
          setIsPaused(false)
        }
        handleSpeechError(error, () => setSpeechRetryKey((key) => key + 1))
      })
  }, [
    environment.id,
    sendEvent,
    teacherResponse.awaiting,
    teacherResponse.current_topic,
    teacherResponse.phase,
    teacherResponse.speech,
    teacherResponse.speech_slides,
    teacherResponse.speech_rate,
    teacherResponse.avatar_state,
    speechRetryKey,
    handleSpeechError,
  ])

  function togglePause() {
    if (isPaused) {
      resumeSpeech()
      setIsPaused(false)
      setAvatarPosture(speakingPosture.current)
    } else {
      pauseSpeech()
      setIsPaused(true)
      setAvatarPosture('idle')
    }
  }

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

  async function openQuiz(mode) {
    if (isBusy) {
      return
    }

    // Closing the quiz only pauses it. Reopen the exact prepared attempt locally,
    // including its selected answers and current question, instead of generating it again.
    if (mode === 'resume' && quiz && quizProgress && !quizResult) {
      setQuizError('')
      setQuizStatus('taking')
      return
    }

    // The quiz covers the lecture, so Regina stops talking.
    actionToken.current += 1
    stopSpeech()
    setIsSpeaking(false)
    setIsPaused(false)
    setSubtitle('')
    setAvatarPosture('idle')

    quizRequest.current?.abort()
    const controller = new AbortController()
    quizRequest.current = controller
    failedQuizAction.current = () => openQuiz(mode)
    setQuizProgress(null)
    setQuizResult(null)
    setQuizError('')
    setQuizErrorAction('retry')
    setQuizStatus('loading')

    try {
      const nextQuiz = await startQuiz(teacherResponse.session_id, mode, controller.signal)
      if (quizRequest.current === controller) {
        setQuiz(nextQuiz)
        setQuizProgress({
          current: 0,
          answers: nextQuiz.questions.map(() => null),
        })
        setQuizStatus('taking')
      }
    } catch (error) {
      if (error.name !== 'AbortError' && quizRequest.current === controller) {
        setQuizError(error.message)
        setQuizStatus('error')
      }
    }
  }

  async function sendQuizAnswers(answers) {
    quizRequest.current?.abort()
    const controller = new AbortController()
    quizRequest.current = controller
    failedQuizAction.current = () => sendQuizAnswers(answers)
    setQuizStatus('submitting')

    try {
      const result = await submitQuiz(teacherResponse.session_id, answers, controller.signal)
      if (quizRequest.current === controller) {
        setQuizResult(result)
        setQuizStatus('results')
      }
    } catch (error) {
      if (error.name !== 'AbortError' && quizRequest.current === controller) {
        const isAnswerValidationError = error.status === 409 && /answer|expected/i.test(error.message)
        setQuizError(error.message)
        setQuizErrorAction(isAnswerValidationError ? 'correct' : 'retry')
        if (isAnswerValidationError) {
          // The attempt remains intact; returning to it lets the student correct the input.
          failedQuizAction.current = () => {
            setQuizError('')
            setQuizStatus('taking')
          }
        }
        setQuizStatus('error')
      }
    }
  }

  function retryQuiz() {
    failedQuizAction.current?.()
  }

  function closeQuiz() {
    quizRequest.current?.abort()
    quizRequest.current = null
    setQuizStatus(null)
  }

  function raiseHand() {
    if (isBusy || !teacherResponse.can_raise_hand) {
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
    if (isBusy || isTranscribing) {
      return
    }

    submitMessage(text)
  }

  function submitMessage(text) {
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

  async function handleVoiceRecording(recording) {
    if (isBusy || isTranscribing || voiceUnavailable) return

    const controller = new AbortController()
    eventRequests.current.add(controller)
    setIsTranscribing(true)

    try {
      const response = await transcribeAudio(
        teacherResponse.session_id,
        recording,
        controller.signal,
      )
      const transcript = response?.text?.trim()
      if (!transcript || /return only the cleaned transcript/i.test(transcript)) {
        throw new Error('We could not hear a response. Please try recording again or type it instead.')
      }

      return transcript
    } catch (error) {
      if (error?.name !== 'AbortError') {
        if (error?.code === 'voice_limit_reached' || error?.status === 429) {
          setVoiceUnavailable(true)
        }
        onError?.(error, 'Could not transcribe your recording')
      }
    } finally {
      eventRequests.current.delete(controller)
      setIsTranscribing(false)
    }

    return ''
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
            // Fill the screen's width and scroll down the page, so a tall A4 page stays readable.
            fitWidth
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
            {isBusy && <img className="session-flow-spinner" src={loadingIcon} alt="" />}
            <span>{stageStatus}</span>
          </div>
        )}

        {isSpeaking && (
          <button
            className={isPaused ? 'speech-pause-button paused' : 'speech-pause-button'}
            type="button"
            onClick={togglePause}
            aria-label={isPaused ? 'Resume Regina' : 'Pause Regina'}
            aria-pressed={isPaused}
          >
            <PauseIcon paused={isPaused} />
            <span>{isPaused ? 'Resume' : 'Pause'}</span>
          </button>
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
        disableCurrentTopic={teacherResponse.awaiting === 'continue'}
        disabled={isBusy || introIsPlaying}
        onOpenLectureSummary={() => setIsLectureSummaryOpen(true)}
        onSelectTopic={chooseTopic}
        outline={teacherResponse.outline}
        pendingTopic={pendingAction?.topicIndex ?? null}
        showLectureSummary={environment.id === 'private-tutor'}
        quizAvailable={teacherResponse.quiz_available}
        // Like the topics: not while Regina is mid-lesson or a request is running.
        quizDisabled={isBusy || teacherResponse.awaiting !== 'nothing'}
        quizLoading={quizStatus === 'loading'}
        quizInProgress={Boolean(quiz && quizProgress && !quizResult && quizStatus === null)}
        quizTaken={quiz !== null}
        onStartQuiz={openQuiz}
      />

      <MessageBar
        awaiting={teacherResponse.awaiting}
        canRaiseHand={teacherResponse.can_raise_hand}
        disabled={isBusy || isTranscribing}
        voiceDisabled={voiceUnavailable}
        voiceProcessing={isTranscribing}
        onRaiseHand={raiseHand}
        onSendMessage={sendMessage}
        onVoiceRecording={handleVoiceRecording}
        onVoiceError={(error) => onError?.(error, 'Voice input is unavailable')}
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

      <QuizPopup
        error={quizError}
        quiz={quiz}
        result={quizResult}
        status={quizStatus}
        progress={quizProgress}
        retryLabel={quizErrorAction === 'correct' ? 'Return to quiz' : 'Try again'}
        onClose={closeQuiz}
        onNewQuiz={() => openQuiz('new')}
        onRetake={() => openQuiz('restart')}
        onRetry={retryQuiz}
        onProgressChange={setQuizProgress}
        onSubmit={sendQuizAnswers}
      />
    </main>
  )
}
