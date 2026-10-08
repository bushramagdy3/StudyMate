import loadingIcon from '../assets/generated-icons/outline-loading.gif'
import playIcon from '../assets/generated-icons/outline-play.png'
import replayIcon from '../assets/generated-icons/outline-replay.png'
import summaryIcon from '../assets/generated-icons/outline-summary.png'

function TopicControlIcon({ kind }) {
  if (kind === 'loading') {
    return <img className="topic-control-icon" src={loadingIcon} alt="" />
  }

  if (kind === 'replay') {
    return <img className="topic-control-icon" src={replayIcon} alt="" />
  }

  return <img className="topic-control-icon" src={playIcon} alt="" />
}

// A small pixel-art padlock for the quiz until every topic is completed.
function QuizLockIcon() {
  return (
    <svg
      className="topic-control-icon quiz-lock-icon"
      viewBox="0 0 10 10"
      shapeRendering="crispEdges"
      aria-hidden="true"
    >
      <path d="M3 1h4v1h1v3H7V2H3v3H2V2h1z" fill="#f0aa78" />
      <path d="M1 5h8v5H1z" fill="#f0aa78" />
      <path d="M2 6h6v3H2z" fill="#8f593f" />
      <path d="M4 6h2v2H4z" fill="#1c1311" />
    </svg>
  )
}

function TopicSummaryIcon() {
  return <img className="topic-summary-icon" src={summaryIcon} alt="" />
}

export function SessionOutline({
  completedTopics = [],
  currentTopic,
  disableCurrentTopic = false,
  disabled = false,
  onOpenLectureSummary,
  onSelectTopic,
  outline = [],
  pendingTopic = null,
  showLectureSummary = false,
  quizAvailable = false,
  quizDisabled = false,
  quizInProgress = false,
  quizLoading = false,
  quizTaken = false,
  onStartQuiz,
}) {
  const quizLocked = !quizAvailable
  const quizButtonDisabled = quizLocked || quizDisabled
  // Like the topics: the name gives the same quiz again, the replay icon new questions.
  const quizTitleLabel = quizLocked
    ? 'Complete every topic to unlock the quiz'
    : quizInProgress
      ? 'Resume quiz'
      : quizTaken
      ? 'Retake the same quiz'
      : 'Start the quiz'
  const quizIconLabel = quizLocked
    ? quizTitleLabel
    : quizInProgress
      ? 'Resume quiz'
      : quizTaken
      ? 'New quiz questions'
      : 'Start the quiz'

  return (
    <aside className="session-outline" aria-label="Session outline">
      <h2>Session Outline</h2>

      <div className="session-topic-list">
        {outline.map((topic) => {
          const isCompleted = completedTopics.includes(topic.index)
          const isActive = currentTopic === topic.index
          const isLoading = pendingTopic === topic.index
          const topicDisabled = disabled || (disableCurrentTopic && isActive)

          return (
            <div
              className={[
                'session-topic',
                isActive ? 'active' : '',
                isCompleted ? 'completed' : '',
                isLoading ? 'pending' : '',
              ].join(' ')}
              key={topic.index}
            >
              <button
                className="session-topic-title"
                disabled={topicDisabled}
                type="button"
                onClick={() => onSelectTopic(topic.index)}
                title={`${isCompleted ? 'Replay' : 'Play'} ${topic.title}`}
                aria-current={isActive ? 'step' : undefined}
              >
                <span>{topic.title}</span>
              </button>

              <div className="session-topic-actions">
                <button
                  className="topic-play-button"
                  disabled={topicDisabled}
                  type="button"
                  onClick={() => onSelectTopic(topic.index)}
                  title={`${isCompleted ? 'Replay' : 'Play'} ${topic.title}`}
                  aria-label={`${isCompleted ? 'Replay' : 'Play'} ${topic.title}`}
                >
                  <TopicControlIcon
                    kind={isLoading ? 'loading' : isCompleted ? 'replay' : 'play'}
                  />
                </button>
              </div>
            </div>
          )
        })}

        {showLectureSummary && (
          <button
            className="session-lecture-summary"
            disabled={disabled}
            type="button"
            onClick={onOpenLectureSummary}
          >
            <TopicSummaryIcon />
            <span>Lecture summary</span>
          </button>
        )}

        <div
          className={[
            'session-topic',
            'session-quiz',
            quizLocked ? 'locked' : '',
            quizLoading ? 'pending' : '',
          ].join(' ')}
        >
          <button
            className="session-topic-title"
            disabled={quizButtonDisabled}
            type="button"
            onClick={() => onStartQuiz(quizInProgress ? 'resume' : quizTaken ? 'restart' : 'new')}
            title={quizTitleLabel}
          >
            <span>Quiz</span>
            {quizLocked && (
              <small className="session-quiz-hint">Finish every topic to unlock</small>
            )}
          </button>

          <div className="session-topic-actions">
            <button
              className="topic-play-button"
              disabled={quizButtonDisabled}
              type="button"
              onClick={() => onStartQuiz(quizInProgress ? 'resume' : 'new')}
              title={quizIconLabel}
              aria-label={quizIconLabel}
            >
              {quizLocked ? (
                <QuizLockIcon />
              ) : (
                <TopicControlIcon
                  kind={quizLoading ? 'loading' : quizTaken ? 'replay' : 'play'}
                />
              )}
            </button>
          </div>
        </div>
      </div>
    </aside>
  )
}
