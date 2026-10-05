import { AppHeader, PixelButton } from './AppHeader.jsx'
import { environments } from '../data/studyMate.js'
import { prepareSession } from '../services/mockService.js'
import { SceneBackdrop } from './SceneBackdrop.jsx'

export function EnvironmentCard({ id, config, selected, onClick }) {
  return <button className={`environment-card ${selected ? 'selected' : ''} env-${id}`} onClick={onClick} aria-label={config.label} aria-pressed={selected}>
    <img className="card-art" src={config.cardArt} alt="" />
    <span className="card-label">{config.label}</span>
  </button>
}

export function PreparationDialog({ progress }) {
  const steps = ['Extracting lecture content', 'Building the topic outline', 'Setting up your AI guide']
  return <div className="preparation-scrim" role="dialog" aria-modal="true" aria-labelledby="preparing-title"><section className="preparation-panel"><h2 id="preparing-title">Preparing your session...</h2><ol>{steps.map((step, index) => <li className={progress >= (index + 1) * 25 ? 'done' : ''} key={step}>{step}</li>)}</ol><div className="progress-track" role="progressbar" aria-label="Session preparation" aria-valuemin="0" aria-valuemax="100" aria-valuenow={progress}><span style={{ width: `${progress}%` }} /></div><p className="sr-only" aria-live="polite">{progress >= 100 ? 'Session ready' : `Preparing session, ${progress}% complete`}</p></section></div>
}

export function EnvironmentSelection({ state, navigate }) {
  const begin = async () => {
    if (!state.environment || state.preparing) return
    state.setPreparing(true); state.setProgress(5)
    await prepareSession((value) => state.setProgress(value))
    state.setPreparing(false); state.setProgress(100); state.setEnded(false); state.setMessages([]); state.setCompleted([]); state.setCurrentTopic(1); state.setMode('explaining')
    navigate(`/session/${state.environment}`)
  }
  return <main className={`scene environment-scene ${state.preparing ? 'is-preparing' : ''}`}>
    <SceneBackdrop />
    <AppHeader onAbout={() => state.setAboutOpen(true)} />
    <section className="environment-content"><h1>Choose Your Environment</h1><div className="environment-grid">{Object.entries(environments).map(([id, config]) => <EnvironmentCard key={id} id={id} config={config} selected={state.environment === id} onClick={() => state.setEnvironment(id)} />)}</div>
      <div className="page-actions"><PixelButton onClick={() => navigate('/upload')}>Back</PixelButton><PixelButton kind="primary" disabled={!state.environment} onClick={begin}>Continue <span aria-hidden="true">▶</span></PixelButton></div>
    </section>
    {state.preparing && <PreparationDialog progress={state.progress} />}
  </main>
}
