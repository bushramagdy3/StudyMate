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
}) {
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
      </div>
    </aside>
  )
}
