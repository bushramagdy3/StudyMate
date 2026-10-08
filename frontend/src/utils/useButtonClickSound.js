import { useEffect } from 'react'

let audioContext

function playTone() {
  try {
    const AudioContext = window.AudioContext || window.webkitAudioContext

    if (!AudioContext) return

    audioContext ??= new AudioContext()
    const context = audioContext
    const start = () => {
      const now = context.currentTime
      const oscillator = context.createOscillator()
      const gain = context.createGain()

      oscillator.type = 'square'
      oscillator.frequency.setValueAtTime(680, now)
      oscillator.frequency.exponentialRampToValueAtTime(940, now + 0.055)
      gain.gain.setValueAtTime(0.0001, now)
      gain.gain.exponentialRampToValueAtTime(0.12, now + 0.004)
      gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.1)

      oscillator.connect(gain).connect(context.destination)
      oscillator.start(now)
      oscillator.stop(now + 0.105)
    }

    if (context.state === 'suspended') {
      context.resume().then(start).catch(() => {})
    } else {
      start()
    }
  } catch {
    // Sound is an optional interaction enhancement.
  }
}

export function useButtonClickSound() {
  useEffect(() => {
    function handleClick(event) {
      if (!event.isTrusted) return

      const button = event.target.closest?.('button')

      if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return

      playTone()
    }

    document.addEventListener('click', handleClick, true)
    return () => document.removeEventListener('click', handleClick, true)
  }, [])
}
