export async function prepareSession(onProgress) {
  for (const progress of [24, 51, 78, 100]) {
    await new Promise((resolve) => window.setTimeout(resolve, 500))
    onProgress(progress)
  }
}

export async function mockReply(text, { wasPaused, topic, persona }) {
  await new Promise((resolve) => window.setTimeout(resolve, 550))
  if (wasPaused) return `Good question. Let's connect it to ${topic}: ${text}`
  return `Thanks for sharing that. ${persona} will keep this in mind as we study ${topic}.`
}
