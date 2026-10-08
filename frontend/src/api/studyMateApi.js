const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const activeSessionRequests = new Set()
const SESSION_START_TIMEOUT_MS = 180_000
const SESSION_EVENT_TIMEOUT_MS = 90_000
const SESSION_READ_TIMEOUT_MS = 30_000
const SESSION_DELETE_TIMEOUT_MS = 20_000

function trackedRequest(externalSignal, timeoutMs, timeoutMessage) {
  const controller = new AbortController()
  activeSessionRequests.add(controller)
  let timedOut = false

  const timeoutId = window.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  let removeExternalAbortListener = () => {}
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort()
    } else {
      const abortFromOutside = () => controller.abort()
      externalSignal.addEventListener('abort', abortFromOutside, { once: true })
      removeExternalAbortListener = () => {
        externalSignal.removeEventListener('abort', abortFromOutside)
      }
    }
  }

  return {
    controller,
    finish() {
      window.clearTimeout(timeoutId)
      removeExternalAbortListener()
      activeSessionRequests.delete(controller)
    },
    throwIfTimedOut(error) {
      if (timedOut) {
        throw new Error(timeoutMessage)
      }

      throw error
    },
  }
}

export function abortAllSessionRequests() {
  activeSessionRequests.forEach((controller) => controller.abort())
  activeSessionRequests.clear()
}

async function readJsonResponse(response) {
  if (response.ok) {
    if (response.status === 204) {
      return null
    }

    return response.json()
  }

  let message = 'Request failed.'

  try {
    const data = await response.json()
    message = data.detail || message
  } catch {
    message = response.statusText || message
  }

  throw new Error(message)
}

export async function startSession({ environmentId, pdfFile, signal }) {
  const request = trackedRequest(
    signal,
    SESSION_START_TIMEOUT_MS,
    'Preparing this session took too long. Please try again with a smaller PDF.',
  )
  const formData = new FormData()
  formData.append('environment', environmentId)
  formData.append('pdf', pdfFile)

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions`, {
      method: 'POST',
      body: formData,
      signal: request.controller.signal,
    })

    return await readJsonResponse(response)
  } catch (error) {
    request.throwIfTimedOut(error)
  } finally {
    request.finish()
  }
}

export async function sendSessionEvent(sessionId, event, signal) {
  const request = trackedRequest(
    signal,
    SESSION_EVENT_TIMEOUT_MS,
    'Regina is taking too long to respond. Please try again.',
  )

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(event),
      signal: request.controller.signal,
    })

    return await readJsonResponse(response)
  } catch (error) {
    request.throwIfTimedOut(error)
  } finally {
    request.finish()
  }
}

export async function getSession(sessionId, signal) {
  const request = trackedRequest(
    signal,
    SESSION_READ_TIMEOUT_MS,
    'Checking the session took too long. Please try again.',
  )

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`, {
      signal: request.controller.signal,
    })

    return await readJsonResponse(response)
  } catch (error) {
    request.throwIfTimedOut(error)
  } finally {
    request.finish()
  }
}

export async function deleteSession(sessionId, signal) {
  const request = trackedRequest(
    signal,
    SESSION_DELETE_TIMEOUT_MS,
    'Closing the session took too long.',
  )

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`, {
      method: 'DELETE',
      signal: request.controller.signal,
    })

    return await readJsonResponse(response)
  } catch (error) {
    request.throwIfTimedOut(error)
  } finally {
    request.finish()
  }
}
