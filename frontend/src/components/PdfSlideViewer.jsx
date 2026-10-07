import { useEffect, useRef, useState } from 'react'
import { GlobalWorkerOptions, getDocument } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

GlobalWorkerOptions.workerSrc = pdfWorkerUrl

export function PdfSlideViewer({ pdfUrl, slideNumber, topicTitle }) {
  const hostRef = useRef(null)
  const canvasRef = useRef(null)
  const [pdfDocument, setPdfDocument] = useState(null)
  const [status, setStatus] = useState(pdfUrl ? 'loading' : 'empty')

  useEffect(() => {
    if (!pdfUrl) {
      setPdfDocument(null)
      setStatus('empty')
      return undefined
    }

    const controller = new AbortController()
    let cancelled = false
    let loadingTask = null

    setPdfDocument(null)
    setStatus('loading')

    async function loadPdf() {
      try {
        // Read the Blob URL on the main thread and hand PDF.js the bytes.
        // This is more reliable than asking the PDF worker to fetch a Blob URL.
        const response = await fetch(pdfUrl, { signal: controller.signal })
        if (!response.ok) {
          throw new Error(`Could not read the uploaded PDF (${response.status}).`)
        }

        const bytes = await response.arrayBuffer()
        if (cancelled) {
          return
        }

        loadingTask = getDocument({ data: new Uint8Array(bytes) })
        const document = await loadingTask.promise

        if (cancelled) {
          await document.destroy()
          return
        }

        setPdfDocument(document)
      } catch (error) {
        if (!cancelled && error?.name !== 'AbortError') {
          console.error(error)
          setStatus('error')
        }
      }
    }

    loadPdf()

    return () => {
      cancelled = true
      controller.abort()
      loadingTask?.destroy()
    }
  }, [pdfUrl])

  useEffect(() => {
    if (!pdfDocument || !hostRef.current || !canvasRef.current) {
      return undefined
    }

    let cancelled = false
    let animationFrame = null
    let renderTask = null
    let renderedPage = null

    async function renderSlide() {
      if (cancelled || !hostRef.current || !canvasRef.current) {
        return
      }

      renderTask?.cancel()
      renderTask = null

      try {
        setStatus('loading')

        const pageNumber = Math.min(
          Math.max(Number(slideNumber) || 1, 1),
          pdfDocument.numPages,
        )
        const page = await pdfDocument.getPage(pageNumber)
        renderedPage = page

        if (cancelled || !hostRef.current || !canvasRef.current) {
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
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
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

        if (!cancelled) {
          setStatus('ready')
        }
      } catch (error) {
        if (
          !cancelled &&
          error?.name !== 'RenderingCancelledException'
        ) {
          console.error(error)
          setStatus('error')
        }
      }
    }

    function scheduleRender() {
      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame)
      }
      animationFrame = requestAnimationFrame(renderSlide)
    }

    let observer = null
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver(scheduleRender)
      observer.observe(hostRef.current)
    }

    scheduleRender()

    return () => {
      cancelled = true
      observer?.disconnect()

      if (animationFrame !== null) {
        cancelAnimationFrame(animationFrame)
      }

      renderTask?.cancel()
      renderedPage?.cleanup()
    }
  }, [pdfDocument, slideNumber])

  useEffect(() => {
    return () => {
      pdfDocument?.destroy()
    }
  }, [pdfDocument])

  if (!pdfUrl) {
    return (
      <div className="pdf-slide-empty">
        <strong>Your uploaded lecture slide</strong>
        <span>Slide {slideNumber} preview appears here</span>
      </div>
    )
  }

  const page = Math.max(Number(slideNumber) || 1, 1)
  const nativeFallbackUrl = `${pdfUrl}#page=${page}&zoom=page-fit&toolbar=0&navpanes=0&scrollbar=0`

  return (
    <div
      className="pdf-slide-canvas-wrap"
      ref={hostRef}
      role="img"
      aria-label={`Slide ${slideNumber}${topicTitle ? `: ${topicTitle}` : ''}`}
    >
      <canvas className="pdf-slide-canvas" ref={canvasRef} />

      {status === 'loading' && (
        <div className="pdf-slide-loading" role="status">
          <span className="pdf-slide-loading-spinner" aria-hidden="true" />
          <span>Loading slide…</span>
        </div>
      )}

      {status === 'error' && (
        <object
          className="pdf-slide-native-fallback"
          data={nativeFallbackUrl}
          type="application/pdf"
          aria-label={`Slide ${slideNumber} fallback viewer`}
        >
          <span className="pdf-slide-error">Could not render this PDF slide.</span>
        </object>
      )}
    </div>
  )
}
