import { useRef, useState } from 'react'

export function FileDropzone({ pdfName, onFile, error }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const choose = (files) => { if (files?.[0]) onFile(files[0]) }
  return <div className="upload-card">
    <button className={`drop-area ${dragging ? 'dragging' : ''}`} type="button" aria-label="Choose a PDF file or drop it here" onClick={() => inputRef.current?.click()} onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files) }}>
      <input ref={inputRef} type="file" accept="application/pdf,.pdf" hidden onChange={(e) => choose(e.target.files)} aria-label="Choose a PDF file" />
      <span className="pdf-mark" aria-hidden="true"><b>PDF</b></span><span>Drag and drop a PDF file here</span><small>or click to browse</small>
    </button>
    <div className={`selected-file ${pdfName ? '' : 'placeholder'}`}>{pdfName && <><span aria-hidden="true">▤</span><span className="file-name">{pdfName}</span><button onClick={() => onFile(null)} aria-label="Remove selected PDF">×</button></>}</div>
    <p className={`upload-help ${error ? 'error' : ''}`} role={error ? 'alert' : undefined}>{error || 'Your PDF slides will be used to generate the interactive study session.'}</p>
  </div>
}
