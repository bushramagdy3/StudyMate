import repeatIcon from '../assets/generated-icons/repeat-transparent.png'

const topics = [
  'Topic 1',
  'Topic 2',
  'Topic 3',
  'Topic 4',
  'Topic 5',
  'Topic 6',
  'Topic 7',
  'Topic 8'
]

export function SessionOutline({ activeTopic, onSelectTopic }) {
  return (
    <aside className="session-outline" aria-label="Session outline">
      <h2>Session Outline</h2>

      <div className="session-topic-list">
        {topics.map((topic, index) => (
          <button
            className={activeTopic === index ? 'session-topic active' : 'session-topic'}
            key={topic}
            type="button"
            onClick={() => onSelectTopic(index)}
          >
            <span>{topic}</span>
            <img src={repeatIcon} alt="" />
          </button>
        ))}
      </div>
    </aside>
  )
}
