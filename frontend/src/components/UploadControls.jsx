import { useRef, useState } from 'react'
import pdfMark from '../assets/pdf-mark.png'
import fileMark from '../assets/file-mark.png'

export function FileDropzone({ pdfName, onFile, error }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const choose = (files) => { if (files?.[0]) onFile(files[0]) }
  return <div className="upload-card">
    <button className={`drop-area ${dragging ? 'dragging' : ''}`} type="button" aria-label="Choose a PDF file or drop it here" onClick={() => inputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files) }}>
      <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(event) => choose(event.target.files)} aria-label="Choose a PDF file" />
      <img className="pdf-mark-art" src={pdfMark} alt="" /><span>Drag and drop a PDF file here</span><small>or click to browse</small>
    </button>
    <div className={`selected-file ${pdfName ? '' : 'placeholder'}`}>{pdfName && <><img className="file-icon" src={fileMark} alt="" /><span className="file-name">{pdfName}</span><button type="button" onClick={() => onFile(null)} aria-label="Remove selected PDF">×</button></>}</div>
    <p className={`upload-help ${error ? 'error' : ''}`} role={error ? 'alert' : undefined}>{error || 'Your PDF slides will be used to generate the interactive study session.'}</p>
  </div>
}
