import { useRef, useState } from 'react'
import background from '../assets/common-background.png'
import closeButton from '../assets/about/close-button.png'
import popupPanel from '../assets/about/popup-panel.png'
import backButton from '../assets/back-button.png'
import continueButton from '../assets/continue-button.png'
import fileIcon from '../assets/generated-icons/file-icon.png'
import mediaLibraryIcon from '../assets/generated-icons/media-library.png'
import pdfMediaIcon from '../assets/generated-icons/media-pdf.png'
import slidesMediaIcon from '../assets/generated-icons/media-slides.png'
import videoMediaIcon from '../assets/generated-icons/media-video.png'
import removeIcon from '../assets/generated-icons/remove-icon.png'
import fileNamePlaceholder from '../assets/upload-pdf-page/file-name-placeholder.png'
import { Screen } from '../components/Screen.jsx'

const sourceKinds = {
  pdf: {
    accept: 'application/pdf,.pdf',
    icon: pdfMediaIcon,
    label: 'PDF slides',
    matcher: (file) => file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'),
    multiple: true,
  },
  presentation: {
    accept: '.ppt,.pptx,application/vnd.ms-powerpoint,application/vnd.openxmlformats-officedocument.presentationml.presentation',
    icon: slidesMediaIcon,
    label: 'PowerPoint slides',
    matcher: (file) => /\.pptx?$/i.test(file.name),
    multiple: true,
  },
  video: {
    accept: 'video/*,.mp4,.m4v,.mov,.mkv,.webm,.avi',
    icon: videoMediaIcon,
    label: 'Video lecture',
    matcher: (file) => file.type.startsWith('video/') || /\.(mp4|m4v|mov|mkv|webm|avi)$/i.test(file.name),
    multiple: false,
  },
}

function sourceLabel(file) {
  return Object.values(sourceKinds).find((kind) => kind.matcher(file))?.label || 'Media source'
}

function fileKey(file) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

export function UploadPdfPage({ mediaFiles, onMediaFilesChange, onBack, onContinue }) {
  const inputs = {
    pdf: useRef(null),
    presentation: useRef(null),
    video: useRef(null),
  }
  const [error, setError] = useState('')
  const [isPickerOpen, setIsPickerOpen] = useState(false)

  function addFiles(files, kind) {
    const requestedKind = sourceKinds[kind]
    const selected = Array.from(files || [])
    const invalid = selected.some((file) => !requestedKind.matcher(file))
    if (invalid) {
      setError(`Choose ${requestedKind.label.toLowerCase()} only.`)
      return
    }

    const currentKeys = new Set(mediaFiles.map(fileKey))
    const newFiles = selected.filter((file) => !currentKeys.has(fileKey(file)))
    if (!newFiles.length) {
      setError('That file is already in this session.')
      return
    }

    setError('')
    onMediaFilesChange([...mediaFiles, ...newFiles])
  }

  function chooseFiles(event, kind) {
    addFiles(event.target.files, kind)
    event.target.value = ''
    setIsPickerOpen(false)
  }

  function dropFiles(event) {
    event.preventDefault()
    const files = Array.from(event.dataTransfer.files)
    const invalid = files.some((file) => !Object.values(sourceKinds).some((kind) => kind.matcher(file)))
    if (invalid) {
      setError('Use PDF, PPT/PPTX, or video files only.')
      return
    }
    const currentKeys = new Set(mediaFiles.map(fileKey))
    const newFiles = files.filter((file) => !currentKeys.has(fileKey(file)))
    if (!newFiles.length) {
      setError('Those files are already in this session.')
      return
    }
    setError('')
    onMediaFilesChange([...mediaFiles, ...newFiles])
  }

  function removeFile(file) {
    setError('')
    onMediaFilesChange(mediaFiles.filter((candidate) => fileKey(candidate) !== fileKey(file)))
  }

  return (
    <Screen background={background} className="upload-page">
      <section className="upload-content">
        <section className="upload-heading">
          <h1 className="page-title">Upload Media</h1>
          <p>Add PDFs, PowerPoints, or a lecture video to build one study session.</p>
        </section>

        <section
          className={mediaFiles.length ? 'upload-panel upload-panel--filled' : 'upload-panel upload-panel--empty'}
        >
          <button
            className="drop-zone"
            type="button"
            onClick={() => setIsPickerOpen(true)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={dropFiles}
          >
            <img className="upload-media-icon" src={mediaLibraryIcon} alt="" />
            <span className="drop-zone-copy">
              <strong>Add learning media</strong>
              <small>PDF, PPT/PPTX, or video</small>
            </span>
          </button>

          {Object.entries(sourceKinds).map(([kind, config]) => (
            <input
              key={kind}
              ref={inputs[kind]}
              hidden
              accept={config.accept}
              multiple={config.multiple}
              type="file"
              onChange={(event) => chooseFiles(event, kind)}
            />
          ))}

          {mediaFiles.length > 0 && (
            <div className="selected-file-list" aria-label="Uploaded media">
              {mediaFiles.map((file) => (
                <div
                  className="selected-file"
                  key={fileKey(file)}
                  style={{ backgroundImage: `url(${fileNamePlaceholder})` }}
                >
                  <img className="selected-file-icon" src={fileIcon} alt="" />
                  <span className="selected-file-copy">
                    <span className="selected-file-name">{file.name}</span>
                    <small>{sourceLabel(file)}</small>
                  </span>
                  <button type="button" onClick={() => removeFile(file)} aria-label={`Remove ${file.name}`}>
                    <img src={removeIcon} alt="" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <p className={error ? 'upload-note error' : 'upload-note'}>
            {error || 'All selected sources are combined into one interactive study session.'}
          </p>
        </section>

        <div className="flow-actions upload-actions">
          <button className="asset-button back-flow-button" type="button" onClick={onBack}>
            <img src={backButton} alt="Back" />
          </button>
          <button className="asset-button continue-flow-button" disabled={!mediaFiles.length} type="button" onClick={onContinue}>
            <img src={continueButton} alt="Continue" />
          </button>
        </div>
      </section>

      {isPickerOpen && (
        <div className="modal-backdrop" role="presentation">
          <section className="about-popup media-picker-popup" style={{ backgroundImage: `url(${popupPanel})` }} role="dialog" aria-modal="true" aria-labelledby="media-picker-title">
            <button className="about-close" type="button" onClick={() => setIsPickerOpen(false)} aria-label="Close">
              <img src={closeButton} alt="" />
            </button>
            <div className="about-popup-content media-picker-content">
              <h2 id="media-picker-title">Add to session</h2>
              <p>Choose the type of source to add.</p>
              <div className="media-picker-actions">
                {Object.entries(sourceKinds).map(([kind, config]) => (
                  <button key={kind} type="button" onClick={() => inputs[kind].current?.click()}>
                    <span className="media-picker-icon"><img src={config.icon} alt="" /></span>
                    <span>{config.label}</span>
                    <small>{config.multiple ? 'Add one or more' : 'Add one video'}</small>
                  </button>
                ))}
              </div>
            </div>
          </section>
        </div>
      )}
    </Screen>
  )
}
