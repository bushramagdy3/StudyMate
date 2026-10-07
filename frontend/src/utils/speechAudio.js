import {
  getPregeneratedSpeechByText,
  getPregeneratedSpeechUrl,
  getPregeneratedSpeech,
} from '../data/pregeneratedSpeech.js'

const backendBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const backendSpeechUrl = `${backendBaseUrl}/api/tutor-speech`

let currentAudio = null
let finishCurrentAudio = null
const speechRequests = new Set()

// Goes up every time speech is stopped, so an older playSpeech() knows to give up.
let speechSequence = 0

// Subtitles show at most this many sentences, and roughly this many characters, at once.
const SUBTITLE_MAX_SENTENCES = 2
const SUBTITLE_MAX_CHARS = 120

/**
 * Splits text into subtitle chunks of 1-2 sentences.
 * Two short sentences share a chunk; a long sentence gets one to itself.
 */
export function splitIntoSubtitles(text) {
  // A sentence ends at . ! or ? followed by a space, so "HTTP/1.1" or "3.5" isn't split.
  const sentences = text.split(/(?<=[.!?]["')\]]?)\s+/)
  const chunks = []
  let current = []

  for (const sentence of sentences.map((part) => part.trim()).filter(Boolean)) {
    const combined = [...current, sentence].join(' ')

    if (
      current.length > 0 &&
      (current.length >= SUBTITLE_MAX_SENTENCES || combined.length > SUBTITLE_MAX_CHARS)
    ) {
      chunks.push(current.join(' '))
      current = [sentence]
    } else {
      current.push(sentence)
    }
  }

  if (current.length > 0) {
    chunks.push(current.join(' '))
  }

  return chunks.length > 0 ? chunks : [text]
}

/**
 * Subtitles for one audio clip. Nothing is shown until the clip actually starts
 * playing (onPlaying); then showChunk(chunkText) is called as the audio
 * progresses, each chunk shown for its share of the clip by length.
 */
function followAudioWithSubtitles(text, showChunk) {
  const chunks = splitIntoSubtitles(text)
  const totalLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const ends = []
  let lengthSoFar = 0

  for (const chunk of chunks) {
    lengthSoFar += chunk.length
    ends.push(lengthSoFar / totalLength)
  }

  let shown = -1
  const show = (index) => {
    if (index !== shown) {
      shown = index
      showChunk(chunks[index])
    }
  }

  let playing = false

  return {
    onPlaying() {
      playing = true

      if (shown === -1) {
        show(0)
      }
    },
    onProgress(fraction) {
      if (!playing) {
        return
      }

      const index = ends.findIndex((end) => fraction < end)
      show(index === -1 ? chunks.length - 1 : index)
    },
  }
}

function stopAudio() {
  if (currentAudio) {
    currentAudio.pause()
    currentAudio.removeAttribute('src')
    currentAudio.load()
    currentAudio = null
  }

  if (finishCurrentAudio) {
    const finish = finishCurrentAudio
    finishCurrentAudio = null
    finish()
  }
}

export function stopSpeech() {
  speechSequence += 1
  speechRequests.forEach((controller) => controller.abort())
  speechRequests.clear()
  stopAudio()
}

function playAudioUrl(audioUrl, shouldRevoke = false, subtitles = null) {
  stopAudio()

  return new Promise((resolve, reject) => {
    const audio = new Audio(audioUrl)
    currentAudio = audio

    if (subtitles) {
      // "playing" fires when sound actually starts (after loading and decoding),
      // so the subtitle never appears before Regina starts speaking.
      audio.onplaying = () => subtitles.onPlaying()
      audio.ontimeupdate = () => {
        if (Number.isFinite(audio.duration) && audio.duration > 0) {
          subtitles.onProgress(audio.currentTime / audio.duration)
        }
      }
    }

    const cleanUp = () => {
      if (shouldRevoke) {
        URL.revokeObjectURL(audioUrl)
      }

      if (currentAudio === audio) {
        currentAudio = null
        finishCurrentAudio = null
      }
    }

    // stopSpeech() ends this clip early: settle the promise instead of leaving it hanging.
    finishCurrentAudio = () => {
      cleanUp()
      resolve()
    }

    audio.onended = () => {
      cleanUp()
      resolve()
    }

    audio.onerror = () => {
      cleanUp()
      reject(new Error(`Could not play audio: ${audioUrl}`))
    }

    audio.play().catch(reject)
  })
}

async function fetchSpeechAudio(text) {
  const controller = new AbortController()
  speechRequests.add(controller)

  try {
    const response = await fetch(backendSpeechUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ text }),
      signal: controller.signal,
    })

    if (!response.ok) {
      throw new Error('Could not generate tutor speech')
    }

    return URL.createObjectURL(await response.blob())
  } finally {
    speechRequests.delete(controller)
  }
}

function prefetchSpeechAudio(text) {
  const audioUrl = fetchSpeechAudio(text)
  // If speech is stopped before this clip is used, its error is expected: don't report it.
  audioUrl.catch(() => {})
  return audioUrl
}

/**
 * Plays the teacher's speech one segment at a time.
 *
 * onSegment(index, subtitle) is called whenever the subtitle changes: index is
 * the segment being spoken (used for raise hand), subtitle is the 1-2 sentences
 * of it being said right now. It's first called with (0, '') to hide the old
 * subtitle while the new audio loads.
 */
export async function playSpeech(speech, environmentId, onSegment = () => {}) {
  stopSpeech()
  const sequence = speechSequence
  const segments = (Array.isArray(speech) ? speech : [speech]).filter(Boolean)

  // Hide the previous subtitle until this speech's audio starts playing.
  onSegment(0, '')

  if (segments.length === 0) {
    return
  }

  // Pre-recorded audio for the whole speech (fixed lines): one subtitle for all of it.
  const fullText = segments.join(' ')
  const pregenerated = getPregeneratedSpeechByText(environmentId, fullText)

  if (pregenerated) {
    const subtitles = followAudioWithSubtitles(fullText, (subtitle) => onSegment(0, subtitle))
    await playAudioUrl(getPregeneratedSpeechUrl(environmentId, pregenerated), false, subtitles)
    return
  }

  // One clip per segment. The next clip is requested while the current one
  // plays, so there's no long gap between segments.
  let nextAudio = prefetchSpeechAudio(segments[0])

  for (let index = 0; index < segments.length; index += 1) {
    const audioUrl = await nextAudio

    if (sequence !== speechSequence) {
      URL.revokeObjectURL(audioUrl)
      return
    }

    nextAudio = index + 1 < segments.length ? prefetchSpeechAudio(segments[index + 1]) : null
    const subtitles = followAudioWithSubtitles(segments[index], (subtitle) => onSegment(index, subtitle))
    await playAudioUrl(audioUrl, true, subtitles)

    if (sequence !== speechSequence) {
      return
    }
  }
}

export function playThinkingSpeech(environmentId) {
  stopSpeech()
  const speech = getPregeneratedSpeech(environmentId, 'thinking')

  return playAudioUrl(getPregeneratedSpeechUrl(environmentId, speech))
}
