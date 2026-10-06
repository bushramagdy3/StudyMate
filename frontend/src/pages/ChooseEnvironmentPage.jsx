import background from '../assets/common-background.png'
import backButton from '../assets/back-button.png'
import continueButton from '../assets/continue-button.png'
import { Screen } from '../components/Screen.jsx'

export function ChooseEnvironmentPage({
  environments,
  selectedEnvironmentId,
  onSelectEnvironment,
  onBack,
  onContinue,
}) {
  const canContinue = Boolean(selectedEnvironmentId)

  return (
    <Screen background={background} className="choose-page">
      <section className="choose-content">
        <h1 className="page-title choose-title">Choose Your Environment</h1>

        <section className="environment-grid" aria-label="Choose an environment">
          {environments.map((environment) => (
            <button
              className="environment-card"
              key={environment.id}
              type="button"
              aria-pressed={environment.id === selectedEnvironmentId}
              onClick={() => onSelectEnvironment(environment.id)}
            >
              <img src={environment.image} alt={environment.name} />
            </button>
          ))}
        </section>

        <div className="flow-actions environment-actions">
          <button className="asset-button back-flow-button" type="button" onClick={onBack}>
            <img src={backButton} alt="Back" />
          </button>
          <button
            className="asset-button continue-flow-button"
            disabled={!canContinue}
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
