import {
  getPregeneratedSpeechByText,
  getPregeneratedSpeechUrl,
  getPregeneratedSpeech,
} from '../data/pregeneratedSpeech.js'

const backendSpeechUrl = 'http://127.0.0.1:8000/api/tutor-speech'

let currentAudio = null
let currentBackendRequest = null
let playToken = 0

export function stopSpeech() {
  playToken += 1

  if (currentBackendRequest) {
    currentBackendRequest.abort()
    currentBackendRequest = null
  }

  if (currentAudio) {
    currentAudio.pause()
    currentAudio.removeAttribute('src')
    currentAudio.load()
    currentAudio = null
  }
}

function playAudioUrl(audioUrl, shouldRevoke = false) {
  stopSpeech()
  const token = playToken

  return new Promise((resolve, reject) => {
    const audio = new Audio(audioUrl)
    currentAudio = audio

    audio.onended = () => {
      if (shouldRevoke) {
        URL.revokeObjectURL(audioUrl)
      }

      if (currentAudio === audio && token === playToken) {
        currentAudio = null
      }

      resolve()
    }

    audio.onerror = () => {
      if (shouldRevoke) {
        URL.revokeObjectURL(audioUrl)
      }

      if (currentAudio === audio && token === playToken) {
        currentAudio = null
      }

      reject(new Error(`Could not play audio: ${audioUrl}`))
    }

    audio.play().catch(reject)
  })
}

async function playBackendSpeech(text) {
  stopSpeech()
  const token = playToken
  const controller = new AbortController()
  currentBackendRequest = controller

  const response = await fetch(backendSpeechUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text }),
    signal: controller.signal,
  })

  if (currentBackendRequest === controller) {
    currentBackendRequest = null
  }

  if (token !== playToken) {
    return
  }

  if (!response.ok) {
    throw new Error('Could not generate tutor speech')
  }

  const audioBlob = await response.blob()

  if (token !== playToken) {
    return
  }

  const audioUrl = URL.createObjectURL(audioBlob)

  return playAudioUrl(audioUrl, true)
}

export async function playSpeech(speech, environmentId) {
  const speechText = Array.isArray(speech) ? speech.join(' ') : speech

  if (!speechText) {
    return
  }

  const pregenerated = getPregeneratedSpeechByText(environmentId, speechText)

  if (pregenerated) {
    await playAudioUrl(getPregeneratedSpeechUrl(environmentId, pregenerated))
    return
  }

  await playBackendSpeech(speechText)
}

export function playThinkingSpeech(environmentId) {
  const speech = getPregeneratedSpeech(environmentId, 'thinking')

  return playAudioUrl(getPregeneratedSpeechUrl(environmentId, speech))
}
