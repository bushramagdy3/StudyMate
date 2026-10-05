import { useEffect, useRef } from 'react'
import brandArt from '../assets/home-brand.png'
import aboutNavArt from '../assets/home-about-nav-label.png'

export function AppHeader({ onAbout, session = false, onEnd }) {
  return <header className="site-header" aria-label="StudyMate header">
    <a className="brand-hit" href="/" onClick={(event) => { event.preventDefault(); window.dispatchEvent(new CustomEvent('studymate-home')) }} aria-label="StudyMate home"><img src={brandArt} alt="StudyMate" /></a>
    {!session && <button className="header-about-hit" onClick={onAbout} aria-label="About StudyMate"><img src={aboutNavArt} alt="" /></button>}
    {session && <button className="header-end-hit" onClick={onEnd}>End Session</button>}
  </header>
}

export function AboutDialog({ onClose, pixelStyle = false }) {
  const dialogRef = useRef(null)
  useEffect(() => {
    const previous = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.focus()
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
      if (event.key === 'Tab') {
        const items = dialogRef.current?.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]), [tabindex]:not([tabindex="-1"])')
        if (!items?.length) return
        const first = items[0]
        const last = items[items.length - 1]
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
      }
    }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = previousOverflow; previous?.focus?.() }
  }, [onClose])
  return <div className="modal-shield" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className={`about-dialog ${pixelStyle ? 'pixel-dialog' : ''}`} role="dialog" aria-modal="true" aria-labelledby="about-heading" tabIndex="-1" ref={dialogRef}>
      <button className="dialog-close" onClick={onClose} aria-label="Close About">X</button>
      <h2 id="about-heading">About StudyMate</h2>
      <p>Turn lecture PDFs into interactive AI-led study sessions.</p>
      <p>Upload your slides, choose a learning environment, and learn through spoken explanations, questions, typed participation, raise-hand interruptions, and repeat controls.</p>
      <strong>Professor | Private Tutor | Study Friend</strong>
    </section>
  </div>
}

export function PixelButton({ children, kind = 'secondary', className = '', ...props }) {
  return <button className={`pixel-button ${kind} ${className}`} {...props}>{children}</button>
}
