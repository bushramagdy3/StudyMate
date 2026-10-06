import logo from '../assets/logo.png'

export function Header({ onHome }) {
  return (
    <header className="site-header">
      <button className="brand-button" type="button" onClick={onHome}>
        <img className="brand-logo" src={logo} alt="" />
        <span className="brand-name">StudyMate</span>
      </button>

      <button className="header-about" type="button">
        About
      </button>
    </header>
  )
}
