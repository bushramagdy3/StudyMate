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

export function SessionOutline({
  completedTopics = [],
  currentTopic,
  disabled = false,
  onSelectTopic,
  outline = [],
  pendingTopic = null,
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
            <button
              className={[
                'session-topic',
                isActive ? 'active' : '',
                isCompleted ? 'completed' : '',
                isLoading ? 'pending' : '',
              ].join(' ')}
              disabled={disabled}
              key={topic.index}
              type="button"
              onClick={() => onSelectTopic(topic.index)}
              title={`${isCompleted ? 'Replay' : 'Play'} ${topic.title}`}
            >
              <span>{topic.title}</span>
              <TopicControlIcon
                kind={isLoading ? 'loading' : isCompleted ? 'replay' : 'play'}
              />
            </button>
          )
        })}
      </div>
    </aside>
  )
}
