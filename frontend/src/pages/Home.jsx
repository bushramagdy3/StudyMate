import { AppHeader, PixelButton } from '../components/AppHeader.jsx'
import { scenes } from '../data/studyMate.js'

export function Home({ onStart, onAbout }) {
  return <main className="scene home-scene" style={{ backgroundImage: `url("${scenes.home}")` }} aria-label="StudyMate home">
    <AppHeader onAbout={onAbout} />
    <section className="home-content">
      <h1 className="home-title">StudyMate</h1>
      <p>Turn lecture slides into an<br />interactive study session.</p>
      <div className="home-actions"><PixelButton kind="primary" onClick={onStart}>Start <span aria-hidden="true">▶</span></PixelButton><PixelButton onClick={onAbout}>About</PixelButton></div>
    </section>
  </main>
}
