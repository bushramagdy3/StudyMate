import bookLoading from '../assets/loading/book-page-turn.gif'
import loadingDots from '../assets/loading/loading-dots.gif'

export function LoadingPopup() {
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
      </section>
    </div>
  )
}
