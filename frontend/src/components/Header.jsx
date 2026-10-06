import logo from '../assets/logo.png'
import heroTitle from '../assets/hero.png'

export function Header({ isSession = false, onEndSession, onHome }) {
  return (
    <header className="site-header">
      <button className="brand-button" type="button" onClick={onHome}>
        <img className="brand-logo" src={logo} alt="" />
        <img className="brand-title-img" src={heroTitle} alt="StudyMate" />
      </button>

      <nav className="header-links" aria-label="Main navigation">
        <button className="header-link" type="button">
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
