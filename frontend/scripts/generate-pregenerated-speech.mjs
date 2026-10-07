import { mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import {
  getPregeneratedSpeech,
  pregeneratedSpeech,
  speechEnvironmentFolders,
} from '../src/data/pregeneratedSpeech.js'

const backendUrl =
  process.env.TTS_BACKEND_URL || 'http://127.0.0.1:8000/api/tutor-speech'

async function generateSpeech(text) {
  const response = await fetch(backendUrl, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text }),
  })

  if (!response.ok) {
    throw new Error(`TTS failed for "${text}": ${await response.text()}`)
  }

  return Buffer.from(await response.arrayBuffer())
}

for (const [environmentId, folder] of Object.entries(speechEnvironmentFolders)) {
  for (const speechKey of Object.keys(pregeneratedSpeech)) {
    const speech = getPregeneratedSpeech(environmentId, speechKey)
    const filePath = resolve('public/audio', folder, speech.fileName)
    const audio = await generateSpeech(speech.text)

    await mkdir(dirname(filePath), { recursive: true })
    await writeFile(filePath, audio)

    console.log(`saved ${filePath}`)
  }
}
