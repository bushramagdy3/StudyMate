import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { environments } from './data/studyMate.js'
import { AboutDialog } from './components/AppHeader.jsx'
import { EnvironmentSelection } from './components/EnvironmentSelection.jsx'
import { LectureSession } from './components/LectureSession.jsx'
import { Home } from './pages/Home.jsx'
import { UploadPage } from './pages/UploadPage.jsx'

function readSession() {
  try { return JSON.parse(sessionStorage.getItem('studymate-session') || '{}') } catch { return {} }
}

function useAppState() {
  const [initial] = useState(() => readSession())
  const [pdf, setPdf] = useState(null)
  const [pdfName, setPdfName] = useState('')
  const [environment, setEnvironment] = useState(initial.environment || '')
  const [preparing, setPreparing] = useState(false)
  const [progress, setProgress] = useState(0)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [currentTopic, setCurrentTopic] = useState(1)
  const [completed, setCompleted] = useState([])
  const [mode, setMode] = useState('explaining')
  const [messages, setMessages] = useState([])
  const [ended, setEnded] = useState(false)
  useEffect(() => { sessionStorage.setItem('studymate-session', JSON.stringify({ environment })) }, [environment])
  return { pdf, setPdf, pdfName, setPdfName, environment, setEnvironment, preparing, setPreparing, progress, setProgress, aboutOpen, setAboutOpen, currentTopic, setCurrentTopic, completed, setCompleted, mode, setMode, messages, setMessages, ended, setEnded }
}

function usePath() {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => { const onPop = () => setPath(window.location.pathname); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop) }, [])
  const navigate = useCallback((to, replace = false) => {
    window.history[replace ? 'replaceState' : 'pushState']({}, '', to)
    setPath(to)
    window.scrollTo(0, 0)
  }, [])
  return [path, navigate]
}

function InvalidRoute({ navigate }) { useEffect(() => navigate('/environment', true), [navigate]); return <main className="route-fallback" aria-live="polite">Returning to environment selection...</main> }

export default function App() {
  const [path, navigate] = usePath()
  const state = useAppState()
  useEffect(() => { const goHome = () => navigate('/'); window.addEventListener('studymate-home', goHome); return () => window.removeEventListener('studymate-home', goHome) }, [navigate])
  const sessionMatch = path.match(/^\/session\/([^/]+)\/?$/)
  const validSession = sessionMatch && Object.hasOwn(environments, sessionMatch[1])
  let page
  if (path === '/' || path === '') page = <Home onStart={() => navigate('/upload')} onAbout={() => state.setAboutOpen(true)} />
  else if (path === '/upload') page = <UploadPage state={state} navigate={navigate} />
  else if (path === '/environment') page = <EnvironmentSelection state={state} navigate={navigate} />
  else if (sessionMatch && validSession) page = <LectureSession key={sessionMatch[1]} environmentId={sessionMatch[1]} state={state} navigate={navigate} />
  else page = <InvalidRoute navigate={navigate} />
  return <>{page}{state.aboutOpen && <AboutDialog pixelStyle={path === '/'} onClose={() => state.setAboutOpen(false)} />}</>
}
