import closeButton from '../assets/about/close-button.png'
import gotItBackground from '../assets/about/got-it-background.png'
import popupPanel from '../assets/about/popup-panel.png'

export function TopicSummaryPopup({ topic, onClose }) {
  if (!topic) return null

  const sections = Array.isArray(topic.summary)
    ? topic.summary
    : typeof topic.summary === 'string' && topic.summary
      ? [{ heading: 'Overview', points: topic.summary.split(/(?<=[.!?])\s+/).filter(Boolean) }]
      : []

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="about-popup topic-summary-popup"
        style={{ backgroundImage: `url(${popupPanel})` }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="topic-summary-title"
      >
        <button className="about-close" type="button" onClick={onClose} aria-label="Close">
          <img src={closeButton} alt="" />
        </button>

        <div className="about-popup-content">
          <h2 id="topic-summary-title">{topic.title}</h2>
          <div className="topic-summary-reading" tabIndex="0">
            {sections.length > 0 ? (
              sections.map((section, index) => (
                <section className="lecture-summary-section" key={`${section.heading}-${index}`}>
                  <h3>{section.heading}</h3>
                  <ul>
                    {section.points.map((point, pointIndex) => (
                      <li key={`${point}-${pointIndex}`}>{point}</li>
                    ))}
                  </ul>
                </section>
              ))
            ) : (
              <p>No revision summary is available for this lecture yet.</p>
            )}
          </div>

          <button
            className="got-it-button"
            style={{ backgroundImage: `url(${gotItBackground})` }}
            type="button"
            onClick={onClose}
          >
            Got it
          </button>
        </div>
      </section>
    </div>
  )
}
