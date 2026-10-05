import { useState } from 'react'
import { AppHeader, PixelButton } from '../components/AppHeader.jsx'
import { FileDropzone } from '../components/UploadControls.jsx'
import { SceneBackdrop } from '../components/SceneBackdrop.jsx'

export function UploadPage({ state, navigate }) {
  const [error, setError] = useState('')
  const selectFile = (file) => {
    if (!file) { state.setPdf(null); state.setPdfName(''); setError(''); return }
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) { state.setPdf(null); state.setPdfName(''); setError('Please choose a PDF file.'); return }
    state.setPdf(file); state.setPdfName(file.name); setError('')
  }
  return <main className="scene upload-scene">
    <SceneBackdrop />
    <AppHeader onAbout={() => state.setAboutOpen(true)} />
    <section className="upload-content"><h1>Upload Lecture Slides</h1><p className="page-subtitle">Upload your PDF slides to create an interactive study session.</p>
      <FileDropzone pdfName={state.pdfName} onFile={selectFile} error={error} />
      <div className="page-actions"><PixelButton onClick={() => navigate('/')}>Back</PixelButton><PixelButton kind="primary" disabled={!state.pdf} onClick={() => navigate('/environment')}>Continue <span aria-hidden="true">▶</span></PixelButton></div>
    </section>
  </main>
}
