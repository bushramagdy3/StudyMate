import logo from '../assets/logo.png'
import heroTitle from '../assets/hero.png'

export function Header({
  isSession = false,
  onAbout,
  onEndSession,
  onHome,
  completedTopics = 0,
  totalTopics = 0,
  progress,
}) {
  // `progress` (0 to 1) also counts the topic in progress; without it, whole topics.
  const fraction = progress ?? (totalTopics > 0 ? completedTopics / totalTopics : 0)
  // Rounded down, so 100% only shows once every topic is finished.
  const percent = Math.floor(fraction * 100)

  return (
    <header className="site-header">
      <button className="brand-button" type="button" onClick={onHome}>
        <img className="brand-logo" src={logo} alt="" />
        <img className="brand-title-img" src={heroTitle} alt="StudyMate" />
      </button>

      {isSession && (
        <div
          className="lecture-progress"
          aria-label={`Lecture progress: ${percent}% (${completedTopics} of ${totalTopics} topics completed)`}
        >
          <div
            className="lecture-progress-track"
            aria-hidden="true"
            style={{ '--lecture-progress': `${percent}%` }}
          >
            <span className="lecture-progress-fill" />
            <span className="lecture-progress-sparkle" />
          </div>
          <span className="lecture-progress-count">
            {percent}%
          </span>
        </div>
      )}

      <nav className="header-links" aria-label="Main navigation">
        <button className="header-link" type="button" onClick={onAbout}>
          About
        </button>

        {isSession && (
          <button className="header-link" type="button" onClick={onEndSession}>
            End Session
          </button>
        )}
      </nav>
    </header>
  )
}
