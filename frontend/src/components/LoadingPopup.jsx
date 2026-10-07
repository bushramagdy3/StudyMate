import bookLoading from '../assets/loading/book-page-turn.gif'
import loadingDots from '../assets/loading/loading-dots.gif'
import { useEffect, useState } from 'react'

const loadingStages = [
  'Reading your PDF and preparing each slide…',
  'Reviewing diagrams, equations, and visual content…',
  'Organizing the lecture topics…',
  'Setting up Regina for your study session…',
]

export function LoadingPopup() {
  const [stageIndex, setStageIndex] = useState(0)

  useEffect(() => {
    const interval = window.setInterval(() => {
      setStageIndex((index) => Math.min(index + 1, loadingStages.length - 1))
    }, 3500)

    return () => window.clearInterval(interval)
  }, [])

  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="loading-popup"
        role="status"
        aria-live="polite"
        aria-label="Loading study session"
      >
        <img className="loading-book" src={bookLoading} alt="" />

        <div className="loading-copy">
          <span>Loading</span>
          <img src={loadingDots} alt="" />
        </div>
        <p className="loading-stage" aria-live="polite">
          {loadingStages[stageIndex]}
        </p>
      </section>
    </div>
  )
}
