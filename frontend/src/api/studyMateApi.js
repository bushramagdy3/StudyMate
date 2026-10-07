const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

const activeSessionRequests = new Set()

function trackedSignal(externalSignal) {
  const controller = new AbortController()
  activeSessionRequests.add(controller)

  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort()
    } else {
      externalSignal.addEventListener('abort', () => controller.abort(), { once: true })
    }
  }

  return controller
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
  const controller = trackedSignal(signal)
  const formData = new FormData()
  formData.append('environment', environmentId)
  formData.append('pdf', pdfFile)

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions`, {
      method: 'POST',
      body: formData,
      signal: controller.signal,
    })

    return await readJsonResponse(response)
  } finally {
    activeSessionRequests.delete(controller)
  }
}

export async function sendSessionEvent(sessionId, event, signal) {
  const controller = trackedSignal(signal)

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(event),
      signal: controller.signal,
    })

    return await readJsonResponse(response)
  } finally {
    activeSessionRequests.delete(controller)
  }
}

export async function getSession(sessionId, signal) {
  const controller = trackedSignal(signal)

  try {
    const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`, {
      signal: controller.signal,
    })

    return await readJsonResponse(response)
  } finally {
    activeSessionRequests.delete(controller)
  }
}

export async function deleteSession(sessionId, signal) {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`, {
    method: 'DELETE',
    signal,
  })

  return readJsonResponse(response)
}
