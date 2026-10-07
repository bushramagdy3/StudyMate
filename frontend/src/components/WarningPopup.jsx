import warningIcon from '../assets/warning-icon.png'

export function WarningPopup({
  title = 'Something went wrong',
  message,
  primaryLabel = 'Got it',
  secondaryLabel,
  onPrimary,
  onSecondary,
}) {
  return (
    <div className="modal-backdrop" role="presentation">
      <section
        className="warning-popup"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="warning-popup-title"
        aria-describedby="warning-popup-message"
      >
        <img className="warning-icon" src={warningIcon} alt="" />
        <h2 id="warning-popup-title">{title}</h2>
        <p id="warning-popup-message">{message}</p>

        <div className="warning-actions">
          {secondaryLabel && (
            <button className="warning-button secondary" type="button" onClick={onSecondary}>
              {secondaryLabel}
            </button>
          )}
          <button className="warning-button primary" type="button" onClick={onPrimary}>
            {primaryLabel}
          </button>
        </div>
      </section>
    </div>
  )
}
