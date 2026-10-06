import closeButton from '../assets/about/close-button.png'
import gotItBackground from '../assets/about/got-it-background.png'
import popupPanel from '../assets/about/popup-panel.png'

export function AboutPopup({ onClose }) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="about-popup"
        style={{ backgroundImage: `url(${popupPanel})` }}
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-popup-title"
      >
        <button className="about-close" type="button" onClick={onClose} aria-label="Close">
          <img src={closeButton} alt="" />
        </button>

        <div className="about-popup-content">
          <h2 id="about-popup-title">About StudyMate</h2>
          <p>
            StudyMate turns your lecture PDFs into interactive AI study sessions.
            Choose your setting, follow the explanation, ask questions, and revisit
            topics at your own pace.
          </p>

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
