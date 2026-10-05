import { PixelButton } from '../components/AppHeader.jsx'
import brandArt from '../assets/home-brand.png'
import leftRoomArt from '../assets/home-room-left.png'
import rightRoomArt from '../assets/home-room-right.png'
import titleArt from '../assets/home-title.png'
import subtitleArt from '../assets/home-subtitle.png'
import aboutButtonLabel from '../assets/home-about-label.png'
import aboutNavLabel from '../assets/home-about-nav-label.png'
import startButtonLabel from '../assets/home-start-label.png'
import startArrow from '../assets/home-start-arrow.png'

export function Home({ onStart, onAbout }) {
  return <main className="scene home-scene" aria-label="StudyMate home">
    <div className="home-art-layer" aria-hidden="true">
      <img className="home-room-left" src={leftRoomArt} alt="" />
      <img className="home-room-right" src={rightRoomArt} alt="" />
    </div>
    <header className="home-header">
      <a className="home-brand" href="/" onClick={(event) => { event.preventDefault(); window.dispatchEvent(new CustomEvent('studymate-home')) }} aria-label="StudyMate home"><img src={brandArt} alt="StudyMate" /></a>
      <button className="home-header-about" onClick={onAbout} aria-label="About StudyMate"><img src={aboutNavLabel} alt="" /><span className="sr-only">About</span></button>
    </header>
    <section className="home-content">
      <h1 className="home-title"><img src={titleArt} alt="" /><span className="sr-only">StudyMate</span></h1>
      <p><img src={subtitleArt} alt="" /><span className="sr-only">Turn lecture slides into an interactive study session.</span></p>
      <div className="home-actions"><PixelButton kind="primary" onClick={onStart} aria-label="Start"><img className="start-label-art" src={startButtonLabel} alt="" /><img className="start-arrow-art" src={startArrow} alt="" /><span className="sr-only">Start</span></PixelButton><PixelButton onClick={onAbout} aria-label="About"><img className="about-label-art" src={aboutButtonLabel} alt="" /><span className="sr-only">About</span></PixelButton></div>
    </section>
  </main>
}
