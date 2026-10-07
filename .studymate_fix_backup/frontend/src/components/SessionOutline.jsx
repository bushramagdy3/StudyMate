import repeatIcon from '../assets/generated-icons/repeat-transparent.png'

export function SessionOutline({
  completedTopics = [],
  currentTopic,
  onSelectTopic,
  outline = [],
}) {
  return (
    <aside className="session-outline" aria-label="Session outline">
      <h2>Session Outline</h2>

      <div className="session-topic-list">
        {outline.map((topic) => (
          <button
            className={[
              'session-topic',
              currentTopic === topic.index ? 'active' : '',
              completedTopics.includes(topic.index) ? 'completed' : '',
            ].join(' ')}
            key={topic.index}
            type="button"
            onClick={() => onSelectTopic(topic.index)}
            title={topic.summary}
          >
            <span>{topic.title}</span>
            <img src={repeatIcon} alt="" />
          </button>
        ))}
      </div>
    </aside>
  )
}
