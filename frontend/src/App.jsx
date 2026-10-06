import { useEffect, useRef, useState } from 'react'
import './App.css'
import { AboutPopup } from './components/AboutPopup.jsx'
import { Header } from './components/Header.jsx'
import { LoadingPopup } from './components/LoadingPopup.jsx'
import { environments } from './data/environments.js'
import { ChooseEnvironmentPage } from './pages/ChooseEnvironmentPage.jsx'
import { HomePage } from './pages/HomePage.jsx'
import { SessionPage } from './pages/SessionPage.jsx'
import { UploadPdfPage } from './pages/UploadPdfPage.jsx'

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
  const [page, setPage] = useState(getInitialPage)
  const [isAboutOpen, setIsAboutOpen] = useState(false)
  const [isLoadingSession, setIsLoadingSession] = useState(false)
  const loadingTimer = useRef(null)
  const [pdfName, setPdfName] = useState(
    () => new URLSearchParams(window.location.search).get('file') || '',
  )
  const [environmentId, setEnvironmentId] = useState(getInitialEnvironmentId)

  const selectedEnvironment =
    environments.find((environment) => environment.id === environmentId) ||
    environments[0]

  useEffect(() => {
    return () => {
      window.clearTimeout(loadingTimer.current)
    }
  }, [])

  function goToPage(nextPage, nextEnvironmentId = environmentId) {
    if (nextPage === 'session' && !environmentExists(nextEnvironmentId)) {
      return
    }

    const nextHash =
      nextPage === 'session' ? `#session/${nextEnvironmentId}` : `#${nextPage}`

    window.history.replaceState(null, '', nextHash)
    setPage(nextPage)
  }

  function openSessionAfterLoading() {
    if (!environmentExists(environmentId)) {
      return
    }

    window.clearTimeout(loadingTimer.current)
    setIsLoadingSession(true)

    loadingTimer.current = window.setTimeout(() => {
      setIsLoadingSession(false)
      goToPage('session', environmentId)
    }, 10000)
  }

  return (
    <>
      <Header
        isSession={page === 'session'}
        onAbout={() => setIsAboutOpen(true)}
        onEndSession={() => goToPage('home')}
        onHome={() => goToPage('home')}
      />

      {page === 'home' && (
        <HomePage
          onAbout={() => setIsAboutOpen(true)}
          onStart={() => goToPage('upload')}
        />
      )}

      {page === 'upload' && (
        <UploadPdfPage
          pdfName={pdfName}
          onPdfNameChange={setPdfName}
          onBack={() => goToPage('home')}
          onContinue={() => goToPage('choose')}
        />
      )}

      {page === 'choose' && (
        <ChooseEnvironmentPage
          environments={environments}
          selectedEnvironmentId={environmentId}
          onSelectEnvironment={setEnvironmentId}
          onBack={() => goToPage('upload')}
          onContinue={openSessionAfterLoading}
        />
      )}

      {page === 'session' && (
        <SessionPage environment={selectedEnvironment} />
      )}

      {isAboutOpen && (
        <AboutPopup onClose={() => setIsAboutOpen(false)} />
      )}

      {isLoadingSession && (
        <LoadingPopup />
      )}
    </>
  )
}

export default App
