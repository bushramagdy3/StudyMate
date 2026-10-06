import { useRef, useState } from 'react'
import background from '../assets/common-background.png'
import backButton from '../assets/back-button.png'
import continueButton from '../assets/continue-button.png'
import fileIcon from '../assets/generated-icons/file-icon.png'
import removeIcon from '../assets/generated-icons/remove-icon.png'
import dropBox from '../assets/upload-pdf-page/box2.png'
import fileNamePlaceholder from '../assets/upload-pdf-page/file-name-placeholder.png'
import panelFrame from '../assets/upload-pdf-page/box1.png'
import { Screen } from '../components/Screen.jsx'

export function UploadPdfPage({
  pdfName,
  onPdfNameChange,
  onBack,
  onContinue,
}) {
  const fileInput = useRef(null)
  const [error, setError] = useState('')
  const hasFile = Boolean(pdfName)

  function handleFile(file) {
    if (!file) {
      return
    }

    const isPdf =
      file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')

    if (!isPdf) {
      setError('Please choose a PDF file.')
      return
    }

    setError('')
    onPdfNameChange(file.name)
  }

  function chooseFile(event) {
    handleFile(event.target.files[0])
  }

  function dropFile(event) {
    event.preventDefault()

    if (!hasFile) {
      handleFile(event.dataTransfer.files[0])
    }
  }

  function removeFile() {
    onPdfNameChange('')
    setError('')

    if (fileInput.current) {
      fileInput.current.value = ''
    }
  }

  return (
    <Screen background={background} className="upload-page">
      <section className="upload-content">
        <section className="upload-heading">
          <h1 className="page-title">Upload Lecture Slides</h1>
          <p>Upload your PDF slides to create an interactive study session.</p>
        </section>

        <section
          className="upload-panel"
          style={{ backgroundImage: `url(${panelFrame})` }}
        >
          <button
            className={hasFile ? 'drop-zone disabled' : 'drop-zone'}
            disabled={hasFile}
            type="button"
            onClick={() => fileInput.current?.click()}
            onDragOver={(event) => event.preventDefault()}
            onDrop={dropFile}
          >
            <img src={dropBox} alt="" />
            <span className="drop-zone-copy">
              <strong>Drag and drop a PDF file here</strong>
              <small>or click to browse</small>
            </span>
          </button>

          <input
            ref={fileInput}
            hidden
            accept="application/pdf,.pdf"
            type="file"
            onChange={chooseFile}
          />

          {hasFile && (
            <div
              className="selected-file"
              style={{ backgroundImage: `url(${fileNamePlaceholder})` }}
            >
              <img className="selected-file-icon" src={fileIcon} alt="" />
              <span className="selected-file-name">{pdfName}</span>
              <button type="button" onClick={removeFile} aria-label="Remove file">
                <img src={removeIcon} alt="" />
              </button>
            </div>
          )}

          <p className={error ? 'upload-note error' : 'upload-note'}>
            {error ||
              'Your PDF slides will be used to generate the interactive study session.'}
          </p>
        </section>

        <div className="flow-actions upload-actions">
          <button className="asset-button back-flow-button" type="button" onClick={onBack}>
            <img src={backButton} alt="Back" />
          </button>
          <button
            className="asset-button continue-flow-button"
            disabled={!hasFile}
            type="button"
            onClick={onContinue}
          >
            <img src={continueButton} alt="Continue" />
          </button>
        </div>
      </section>
    </Screen>
  )
}
