function TopicControlIcon({ kind }) {
  if (kind === 'loading') {
    return (
      <svg
        className="topic-control-icon topic-control-icon-loading"
        viewBox="0 0 32 32"
        aria-hidden="true"
      >
        <circle className="topic-spinner-track" cx="16" cy="16" r="10" />
        <path className="topic-spinner-head" d="M16 6a10 10 0 0 1 10 10" />
      </svg>
    )
  }

  if (kind === 'replay') {
    return (
      <svg
        className="topic-control-icon"
        viewBox="0 0 32 32"
        aria-hidden="true"
      >
        <path
          d="M9.2 10.2A10 10 0 1 1 6 17.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.4"
          strokeLinecap="round"
        />
        <path d="M5 6v8h8z" fill="currentColor" />
      </svg>
    )
  }

  return (
    <svg
      className="topic-control-icon"
      viewBox="0 0 32 32"
      aria-hidden="true"
    >
      <path d="M10 7.5 25 16 10 24.5z" fill="currentColor" />
    </svg>
  )
}

function TopicSummaryIcon() {
  return (
    <svg className="topic-summary-icon" viewBox="0 0 32 32" aria-hidden="true">
      <path d="M8 4h12l4 4v20H8z" fill="none" stroke="currentColor" strokeWidth="2.6" />
      <path d="M20 4v5h5M12 14h8M12 19h8M12 24h5" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="square" />
    </svg>
  )
}

export function SessionOutline({
  completedTopics = [],
  currentTopic,
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
                disabled={disabled}
                type="button"
                onClick={() => onSelectTopic(topic.index)}
                title={`${isCompleted ? 'Replay' : 'Play'} ${topic.title}`}
              >
                <span>{topic.title}</span>
              </button>

              <div className="session-topic-actions">
                <button
                  className="topic-play-button"
                  disabled={disabled}
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
