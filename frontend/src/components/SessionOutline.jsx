import repeatIcon from '../assets/generated-icons/repeat-transparent.png'

export function SessionOutline({
  completedTopics = [],
  currentTopic,
  disabled = false,
  onSelectTopic,
  outline = [],
}) {
  return (
    <aside className="session-outline" aria-label="Session outline">
      <h2>Session Outline</h2>

      <div className="session-topic-list">
        {outline.map((topic) => {
          const isCompleted = completedTopics.includes(topic.index)
          const isActive = currentTopic === topic.index

          return (
            <button
              className={[
                'session-topic',
                isActive ? 'active' : '',
                isCompleted ? 'completed' : '',
              ].join(' ')}
              disabled={disabled}
              key={topic.index}
              type="button"
              onClick={() => onSelectTopic(topic.index)}
              title={`${isCompleted ? 'Replay' : 'Play'} ${topic.title}`}
            >
              <span>{topic.title}</span>

              {isCompleted ? (
                <img src={repeatIcon} alt="Replay" />
              ) : (
                <span className="topic-play-icon" aria-label="Play">
                  ▶
                </span>
              )}
            </button>
          )
        })}
      </div>
    </aside>
  )
}
