const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000'

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
  const formData = new FormData()
  formData.append('environment', environmentId)
  formData.append('pdf', pdfFile)

  const response = await fetch(`${apiBaseUrl}/api/sessions`, {
    method: 'POST',
    body: formData,
    signal,
  })

  return readJsonResponse(response)
}

export async function sendSessionEvent(sessionId, event, signal) {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}/events`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(event),
    signal,
  })

  return readJsonResponse(response)
}

export async function getSession(sessionId, signal) {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`, {
    signal,
  })

  return readJsonResponse(response)
}

export async function deleteSession(sessionId, signal) {
  const response = await fetch(`${apiBaseUrl}/api/sessions/${sessionId}`, {
    method: 'DELETE',
    signal,
  })

  return readJsonResponse(response)
}
