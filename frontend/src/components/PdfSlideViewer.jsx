import { useEffect, useRef, useState } from 'react'
import { GlobalWorkerOptions, getDocument } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export function PdfSlideViewer({ pdfUrl, slideNumber, topicTitle }) {
  const hostRef = useRef(null)
  const canvasRef = useRef(null)
  const [pdfDocument, setPdfDocument] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!pdfUrl) {
      setPdfDocument(null)
      setError('')
      return undefined
    }

    let cancelled = false
    const loadingTask = getDocument(pdfUrl)

    loadingTask.promise
      .then((document) => {
        if (cancelled) {
          document.destroy()
          return
        }

        setPdfDocument(document)
        setError('')
      })
      .catch((loadError) => {
        if (!cancelled) {
          console.error(loadError)
          setPdfDocument(null)
          setError('Could not render this PDF slide.')
        }
      })

    return () => {
      cancelled = true
      loadingTask.destroy()
    }
  }, [pdfUrl])

  useEffect(() => {
    if (!pdfDocument || !hostRef.current || !canvasRef.current) {
      return undefined
    }

    let cancelled = false
    let animationFrame = null
    let renderTask = null

    async function renderSlide() {
      if (cancelled || !hostRef.current || !canvasRef.current) {
        return
      }

      if (renderTask) {
        renderTask.cancel()
        renderTask = null
      }

      try {
        const pageNumber = Math.min(
          Math.max(Number(slideNumber) || 1, 1),
          pdfDocument.numPages,
        )
        const page = await pdfDocument.getPage(pageNumber)

        if (cancelled) {
          return
        }

        const host = hostRef.current
        const canvas = canvasRef.current
        const baseViewport = page.getViewport({ scale: 1 })
        const availableWidth = Math.max(host.clientWidth, 1)
        const availableHeight = Math.max(host.clientHeight, 1)
        const scale = Math.min(
          availableWidth / baseViewport.width,
          availableHeight / baseViewport.height,
        )
        const viewport = page.getViewport({ scale: Math.max(scale, 0.1) })
        const pixelRatio = window.devicePixelRatio || 1
        const context = canvas.getContext('2d', { alpha: false })

        canvas.width = Math.max(1, Math.floor(viewport.width * pixelRatio))
        canvas.height = Math.max(1, Math.floor(viewport.height * pixelRatio))
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`

        renderTask = page.render({
          canvasContext: context,
          viewport,
          background: '#fdfaf4',
          transform:
            pixelRatio === 1
              ? undefined
              : [pixelRatio, 0, 0, pixelRatio, 0, 0],
        })

        await renderTask.promise
        renderTask = null
        setError('')
      } catch (renderError) {
        if (
          !cancelled &&
          renderError?.name !== 'RenderingCancelledException'
        ) {
          console.error(renderError)
          setError('Could not render this PDF slide.')
        }
      }
    }

    function scheduleRender() {
      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame)
      }

      animationFrame = requestAnimationFrame(renderSlide)
    }

    const observer = new ResizeObserver(scheduleRender)
    observer.observe(hostRef.current)
    scheduleRender()

    return () => {
      cancelled = true
      observer.disconnect()

      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame)
      }

      if (renderTask) {
        renderTask.cancel()
      }
    }
  }, [pdfDocument, slideNumber])

  if (!pdfUrl) {
    return (
      <div className="pdf-slide-empty">
        <strong>Your uploaded lecture slide</strong>
        <span>Slide {slideNumber} preview appears here</span>
      </div>
    )
  }

  return (
    <div
      className="pdf-slide-canvas-wrap"
      ref={hostRef}
      role="img"
      aria-label={`Slide ${slideNumber}${topicTitle ? `: ${topicTitle}` : ''}`}
    >
      <canvas className="pdf-slide-canvas" ref={canvasRef} />
      {error && <span className="pdf-slide-error">{error}</span>}
    </div>
  )
}
