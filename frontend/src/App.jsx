import { useCallback, useEffect, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import './App.css'
import { AboutPopup } from './components/AboutPopup.jsx'
import { Header } from './components/Header.jsx'
import { LoadingPopup } from './components/LoadingPopup.jsx'
import { WarningPopup } from './components/WarningPopup.jsx'
import { BackgroundMusic } from './components/BackgroundMusic.jsx'
import {
  abortAllSessionRequests,
  deleteSession,
  startSession,
} from './api/studyMateApi.js'
import { environments } from './data/environments.js'
import { ChooseEnvironmentPage } from './pages/ChooseEnvironmentPage.jsx'
import { HomePage } from './pages/HomePage.jsx'
import { SessionPage } from './pages/SessionPage.jsx'
import { UploadPdfPage } from './pages/UploadPdfPage.jsx'
import { stopSpeech } from './utils/speechAudio.js'
import { useButtonClickSound } from './utils/useButtonClickSound.js'

const pages = new Set(['home', 'upload', 'choose', 'session'])

function environmentExists(environmentId) {
  return environments.some((environment) => environment.id === environmentId)
}

function getInitialPage() {
  const [hashPage] = window.location.hash.replace('#', '').split('/')

  return pages.has(hashPage) ? hashPage : 'home'
}

function getInitialEnvironmentId() {
  const [, hashEnvironmentId] = window.location.hash.replace('#', '').split('/')
  const queryEnvironmentId = new URLSearchParams(window.location.search).get('env')
  const environmentId = hashEnvironmentId || queryEnvironmentId

  return environmentExists(environmentId) ? environmentId : ''
}

function App() {
  useButtonClickSound()
  const [page, setPage] = useState(getInitialPage)
  const [isAboutOpen, setIsAboutOpen] = useState(false)
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const [dialog, setDialog] = useState(null)
  const [pdfName, setPdfName] = useState(
    () => new URLSearchParams(window.location.search).get('file') || '',
  )
  const [pdfFile, setPdfFile] = useState(null)
  const [pdfUrl, setPdfUrl] = useState('')
  const pdfUrlRef = useRef('')
  const startSessionRequest = useRef(null)
  const [environmentId, setEnvironmentId] = useState(getInitialEnvironmentId)
  const [teacherResponse, setTeacherResponse] = useState(null)

  const selectedEnvironment =
    environments.find((environment) => environment.id === environmentId) ||
    environments[0]
  const displayedPage = page === 'session' && !teacherResponse ? 'home' : page

  const showError = useCallback((error, title = 'Something went wrong') => {
    if (error?.name === 'AbortError') {
      return
    }

    console.error(error)
    setDialog({
      kind: 'error',
      title,
      message:
        error?.message ||
        (typeof error === 'string' ? error : 'Please try again in a moment.'),
    })
  }, [])

  useEffect(() => {
    function handleUnhandledRejection(event) {
      showError(event.reason)
    }

    window.addEventListener('unhandledrejection', handleUnhandledRejection)
    return () => {
      window.removeEventListener('unhandledrejection', handleUnhandledRejection)
    }
  }, [showError])

  useEffect(() => {
    return () => {
      abortStartSession()

      if (pdfUrlRef.current) {
        URL.revokeObjectURL(pdfUrlRef.current)
      }
    }
  }, [])

  function abortStartSession() {
    if (startSessionRequest.current) {
      startSessionRequest.current.abort()
      startSessionRequest.current = null
    }
  }

  function changePdfFile(file) {
    if (pdfUrlRef.current) {
      URL.revokeObjectURL(pdfUrlRef.current)
      pdfUrlRef.current = ''
    }

    if (!file) {
      setPdfFile(null)
      setPdfUrl('')
      return
    }

    setPdfFile(file)
    const nextPdfUrl = URL.createObjectURL(file)
    pdfUrlRef.current = nextPdfUrl
    setPdfUrl(nextPdfUrl)
  }

  function goToPage(nextPage, nextEnvironmentId = environmentId) {
    if (nextPage === 'session' && !environmentExists(nextEnvironmentId)) {
      return
    }

    if (isLoadingSession && nextPage !== 'session') {
      abortStartSession()
      setIsLoadingSession(false)
    }

    const nextHash =
      nextPage === 'session' ? `#session/${nextEnvironmentId}` : `#${nextPage}`

    window.history.replaceState(null, '', nextHash)
    setPage(nextPage)
  }

  async function openSessionAfterLoading() {
    if (!environmentExists(environmentId) || !pdfFile) {
      return
    }

    setDialog(null)
    setIsLoadingSession(true)
    abortStartSession()

    const controller = new AbortController()
    startSessionRequest.current = controller

    try {
      const response = await startSession({
        environmentId,
        pdfFile,
        signal: controller.signal,
      })

      if (startSessionRequest.current !== controller) {
        return
      }

      startSessionRequest.current = null
      setTeacherResponse(response)
      setIsLoadingSession(false)
      goToPage('session', environmentId)
    } catch (error) {
      if (error.name === 'AbortError') {
        return
      }

      if (startSessionRequest.current === controller) {
        startSessionRequest.current = null
      }

      setIsLoadingSession(false)
      setDialog({
        kind: 'start-error',
        title: 'Could not start the session',
        message: error.message || 'Please check your PDF and try again.',
      })
    }
  }

  function requestEndSession() {
    setDialog({
      kind: 'end-session',
      title: 'Leave this session?',
      message: 'Your current study session will be closed.',
    })
  }

  function endSession() {
    const sessionId = teacherResponse?.session_id

    // Commit the home screen before media/request cleanup can run any callbacks.
    window.history.replaceState(null, '', '#home')
    flushSync(() => {
      setPage('home')
      setTeacherResponse(null)
      setIsLoadingSession(false)
      setIsAboutOpen(false)
    })

    stopSpeech()
    abortAllSessionRequests()
    abortStartSession()

    if (!sessionId) {
      return
    }

    // Session deletion is cleanup only. It must not hold the UI on a blank page.
    deleteSession(sessionId).catch((error) =>
      showError(error, 'Could not close the session'),
    )
  }

  function handleDialogPrimary() {
    const dialogKind = dialog?.kind
    setDialog(null)

    if (dialogKind === 'end-session') {
      endSession()
    } else if (dialogKind === 'start-error') {
      openSessionAfterLoading()
    }
  }

  return (
    <>
      <BackgroundMusic track={displayedPage === 'session' ? environmentId : 'home'} />
      <Header
        completedTopics={teacherResponse?.completed_topics.length || 0}
        progress={teacherResponse?.lecture_progress}
        isSession={displayedPage === 'session'}
        onAbout={() => setIsAboutOpen(true)}
        onEndSession={requestEndSession}
        onHome={displayedPage === 'session' ? requestEndSession : () => goToPage('home')}
        totalTopics={teacherResponse?.outline.length || 0}
      />

      {displayedPage === 'home' && (
        <HomePage
          onAbout={() => setIsAboutOpen(true)}
          onStart={() => goToPage('upload')}
        />
      )}

      {displayedPage === 'upload' && (
        <UploadPdfPage
          onPdfFileChange={changePdfFile}
          pdfName={pdfName}
          onPdfNameChange={setPdfName}
          onBack={() => goToPage('home')}
          onContinue={() => goToPage('choose')}
        />
      )}

      {displayedPage === 'choose' && (
        <ChooseEnvironmentPage
          environments={environments}
          selectedEnvironmentId={environmentId}
          onSelectEnvironment={setEnvironmentId}
          onBack={() => goToPage('upload')}
          onContinue={openSessionAfterLoading}
        />
      )}

      {displayedPage === 'session' && teacherResponse && (
        <SessionPage
          environment={selectedEnvironment}
          initialTeacherResponse={teacherResponse}
          pdfUrl={pdfUrl}
          onTeacherResponseChange={setTeacherResponse}
          onError={showError}
        />
      )}

      {isAboutOpen && (
        <AboutPopup onClose={() => setIsAboutOpen(false)} />
      )}

      {isLoadingSession && (
        <LoadingPopup />
      )}

      {dialog && (
        <WarningPopup
          title={dialog.title}
          message={dialog.message}
          primaryLabel={
            dialog.kind === 'end-session'
              ? 'Leave'
              : dialog.kind === 'start-error'
                ? 'Try again'
                : 'Got it'
          }
          secondaryLabel={
            dialog.kind === 'end-session'
              ? 'Stay'
              : dialog.kind === 'start-error'
                ? 'Cancel'
                : undefined
          }
          onPrimary={handleDialogPrimary}
          onSecondary={() => setDialog(null)}
        />
      )}
    </>
  )
}

export default App
