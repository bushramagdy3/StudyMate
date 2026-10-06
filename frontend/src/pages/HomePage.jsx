import background from '../assets/home-page/background.png'
import aboutButton from '../assets/home-page/about-button.png'
import startButton from '../assets/home-page/start-button.png'
import heroTitle from '../assets/hero.png'
import { Screen } from '../components/Screen.jsx'

export function HomePage({ onStart }) {
  return (
    <Screen background={background} className="home-page">
      <section className="home-content">
        <section className="home-copy" aria-labelledby="home-title">
          <img className="home-title-img" src={heroTitle} alt="StudyMate" />
          <h1 id="home-title" className="visually-hidden">
            StudyMate
          </h1>
          <p>Turn lecture slides into an interactive study session.</p>
        </section>

        <div className="home-actions">
          <button className="asset-button home-start" type="button" onClick={onStart}>
            <img src={startButton} alt="Start" />
          </button>
          <button className="asset-button home-about" type="button">
            <img src={aboutButton} alt="About" />
          </button>
        </div>
      </section>
    </Screen>
  )
}
