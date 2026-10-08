import {
  getPregeneratedSpeechByText,
  getPregeneratedSpeechUrl,
  getPregeneratedSpeech,
} from '../data/pregeneratedSpeech.js'

const backendBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
const backendSpeechUrl = `${backendBaseUrl}/api/tutor-speech`
const SPEECH_REQUEST_TIMEOUT_MS = 45_000

let currentAudio = null
let finishCurrentAudio = null
const speechRequests = new Set()

// Goes up every time speech is stopped, so an older playSpeech() knows to give up.
let speechSequence = 0

// Dynamic speech is played one sentence at a time so each subtitle has exact
// audio start/end boundaries.
const SUBTITLE_MAX_SENTENCES = 1
const SUBTITLE_MAX_CHARS = 120
const FISH_DIRECTION_TAG = /\[[^\]\r\n]{1,48}\]\s*/g

export function textForSubtitle(text) {
  return text.replace(FISH_DIRECTION_TAG, '').replace(/\s{2,}/g, ' ').trim()
}

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
function followAudioWithSubtitles(text, showChunk, clearSubtitle) {
  return {
    onPlaying() {
      showChunk(textForSubtitle(text))
    },
    onEnd() {
      clearSubtitle()
    },
  }
}

function stopAudio() {
  const audio = currentAudio
  const finish = finishCurrentAudio
  currentAudio = null
  finishCurrentAudio = null

  if (audio) {
    try {
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
    } catch (error) {
      console.warn('Could not fully release the previous audio element.', error)
    }
  }

  if (finish) {
    finish()
  }
}

export function stopSpeech() {
  speechSequence += 1
  speechRequests.forEach((controller) => {
    try {
      controller.abort()
    } catch (error) {
      console.warn('Could not abort a speech request.', error)
    }
  })
  speechRequests.clear()
  stopAudio()
}

function playAudioUrl(audioUrl, shouldRevoke = false, subtitles = null, callbacks = {}) {
  stopAudio()

  return new Promise((resolve, reject) => {
    const audio = new Audio(audioUrl)
    currentAudio = audio

    if (subtitles) {
      // "playing" fires when sound actually starts (after loading and decoding),
      // so the subtitle never appears before Regina starts speaking.
      audio.onplaying = () => {
        callbacks.onStart?.()
        subtitles.onPlaying()
      }
    }

    const cleanUp = () => {
      subtitles?.onEnd()

      if (shouldRevoke) {
        URL.revokeObjectURL(audioUrl)
      }

      if (currentAudio === audio) {
        currentAudio = null
        finishCurrentAudio = null
      }
    }

    // Reject as an abort so a stopped clip can never advance the lecture flow.
    finishCurrentAudio = () => {
      cleanUp()
      reject(new DOMException('Speech stopped', 'AbortError'))
    }

    audio.onended = () => {
      cleanUp()
      resolve()
    }

    audio.onerror = () => {
      cleanUp()
      reject(new Error(`Could not play audio: ${audioUrl}`))
    }

    audio.play().catch((error) => {
      cleanUp()
      reject(error)
    })
  })
}

async function fetchSpeechAudio(text) {
  const controller = new AbortController()
  speechRequests.add(controller)
  let timedOut = false
  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, SPEECH_REQUEST_TIMEOUT_MS)

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
      let message = 'Could not generate Regina’s speech.'

      try {
        const data = await response.json()
        message = data.detail || message
      } catch {
        message = response.statusText || message
      }

      throw new Error(message)
    }

    return URL.createObjectURL(await response.blob())
  } catch (error) {
    if (timedOut) {
      throw new Error('Generating Regina’s speech took too long. Please try again.', {
        cause: error,
      })
    }

    throw error
  } finally {
    window.clearTimeout(timeoutId)
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
export async function playSpeech(speech, environmentId, callbacks = {}) {
  stopSpeech()
  const sequence = speechSequence
  const sourceSegments = (Array.isArray(speech) ? speech : [speech]).filter(Boolean)
  const onSegment = typeof callbacks === 'function'
    ? callbacks
    : callbacks.onSegment || (() => {})
  const onWaiting = typeof callbacks === 'function'
    ? () => {}
    : callbacks.onWaiting || (() => {})
  const onStart = typeof callbacks === 'function'
    ? () => {}
    : callbacks.onStart || (() => {})
  const onError = typeof callbacks === 'function'
    ? () => {}
    : callbacks.onError || (() => {})

  // Hide the previous subtitle until this speech's audio starts playing.
  onSegment(0, '')

  if (sourceSegments.length === 0) {
    return
  }

  // Pre-recorded audio for the whole speech (fixed lines): one subtitle for all of it.
  const fullText = sourceSegments.join(' ')
  const pregenerated = getPregeneratedSpeechByText(environmentId, fullText)

  if (pregenerated) {
    onWaiting()
    const subtitles = followAudioWithSubtitles(
      fullText,
      (subtitle) => onSegment(0, subtitle),
      () => onSegment(0, ''),
    )
    try {
      await playAudioUrl(
        getPregeneratedSpeechUrl(environmentId, pregenerated),
        false,
        subtitles,
        { onStart },
      )
    } catch (error) {
      onError(error)
      throw error
    }
    return
  }

  const segments = sourceSegments.flatMap((text, sourceIndex) =>
    splitIntoSubtitles(text).map((sentence) => ({ text: sentence, sourceIndex })),
  )

  // One clip per segment. The next clip is requested while the current one
  // plays, so there's no long gap between segments.
  let nextAudio = prefetchSpeechAudio(segments[0].text)

  for (let index = 0; index < segments.length; index += 1) {
    onWaiting()
    let audioUrl
    try {
      audioUrl = await nextAudio
    } catch (error) {
      onError(error)
      throw error
    }

    if (sequence !== speechSequence) {
      URL.revokeObjectURL(audioUrl)
      return
    }

    nextAudio = index + 1 < segments.length
      ? prefetchSpeechAudio(segments[index + 1].text)
      : null
    const subtitles = followAudioWithSubtitles(
      segments[index].text,
      (subtitle) => onSegment(segments[index].sourceIndex, subtitle),
      () => onSegment(segments[index].sourceIndex, ''),
    )
    try {
      await playAudioUrl(audioUrl, true, subtitles, { onStart })
    } catch (error) {
      onError(error)
      throw error
    }

    if (sequence !== speechSequence) {
      return
    }
  }
}

export function playThinkingSpeech(environmentId, callbacks = {}) {
  stopSpeech()
  const speech = getPregeneratedSpeech(environmentId, 'thinking')
  const onSegment = callbacks.onSegment || (() => {})
  const subtitles = followAudioWithSubtitles(
    speech.text,
    (subtitle) => onSegment(0, subtitle),
    () => onSegment(0, ''),
  )

  callbacks.onWaiting?.()
  return playAudioUrl(
    getPregeneratedSpeechUrl(environmentId, speech),
    false,
    subtitles,
    { onStart: callbacks.onStart },
  )
}
