import { useState } from 'react'
import './App.css'
import { Header } from './components/Header.jsx'
import { environments } from './data/environments.js'
import { ChooseEnvironmentPage } from './pages/ChooseEnvironmentPage.jsx'
import { HomePage } from './pages/HomePage.jsx'
import { UploadPdfPage } from './pages/UploadPdfPage.jsx'

const pages = new Set(['home', 'upload', 'choose'])

function getInitialPage() {
  const hashPage = window.location.hash.replace('#', '')

  return pages.has(hashPage) ? hashPage : 'home'
}

function App() {
  const [page, setPage] = useState(getInitialPage)
  const [pdfName, setPdfName] = useState(
    () => new URLSearchParams(window.location.search).get('file') || '',
  )
  const [environmentId, setEnvironmentId] = useState('lecture-hall')

  function goToPage(nextPage) {
    window.history.replaceState(null, '', `#${nextPage}`)
    setPage(nextPage)
  }

  return (
    <>
      <Header onHome={() => goToPage('home')} />

      {page === 'home' && (
        <HomePage
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
          onContinue={() => {}}
        />
      )}
    </>
  )
}

export default App
