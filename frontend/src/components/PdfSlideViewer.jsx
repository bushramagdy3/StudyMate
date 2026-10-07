export function PdfSlideViewer({ pdfUrl, slideNumber, topicTitle }) {
  if (!pdfUrl) {
    return (
      <div className="pdf-slide-empty">
        <strong>Your uploaded lecture slide</strong>
        <span>Slide {slideNumber} preview appears here</span>
      </div>
    )
  }

  const slideUrl = `${pdfUrl}#page=${slideNumber}&zoom=page-fit&toolbar=0&navpanes=0&scrollbar=0`

  return (
    <iframe
      className="pdf-slide-frame"
      src={slideUrl}
      title={`Slide ${slideNumber}${topicTitle ? `: ${topicTitle}` : ''}`}
    />
  )
}
