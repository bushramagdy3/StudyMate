export const pregeneratedSpeech = {
  welcome: {
    fileName: 'welcome.mp3',
    text: {
      'lecture-hall':
        "[reassuring] Welcome. I am Professor Regina. Let us begin by looking carefully at today's lecture.",
      'private-tutor':
        '[reassuring] Hi, I am Regina. We will take this one step at a time.',
      'study-cafe':
        "[excited] Hey, I am Regina. Let's go through this together and make it make sense.",
    },
  },
  handRaisePrompt: {
    fileName: 'what-would-you-like-to-ask.mp3',
    text: {
      'lecture-hall': '[reassuring] Yes, go ahead. What question would you like to raise?',
      'private-tutor': '[reassuring] Of course. What are you wondering about?',
      'study-cafe': '[thoughtful] Yeah, tell me what part feels confusing.',
    },
  },
  thinking: {
    fileName: 'let-me-think.mp3',
    text: {
      'lecture-hall': '[thoughtful] Let me consider that for a moment.',
      'private-tutor': '[thoughtful] Let me think that through for a second.',
      'study-cafe': '[thoughtful] Hmm, give me a second to think about that.',
    },
  },
}

export const speechEnvironmentFolders = {
  'lecture-hall': 'lecture-hall',
  'private-tutor': 'private-tutor',
  'study-cafe': 'study-cafe',
}

export function getPregeneratedSpeech(environmentId, speechKey) {
  const speech = pregeneratedSpeech[speechKey]

  if (!speech) {
    return null
  }

  return {
    fileName: speech.fileName,
    text: speech.text[environmentId] || speech.text['private-tutor'],
  }
}

export function getPregeneratedSpeechByText(environmentId, text) {
  return Object.values(pregeneratedSpeech).find((speech) => {
    const environmentText = speech.text[environmentId] || speech.text['private-tutor']

    return environmentText === text
  })
}

export function getPregeneratedSpeechUrl(environmentId, speech) {
  const folder = speechEnvironmentFolders[environmentId] || 'private-tutor'

  return `/audio/${folder}/${speech.fileName}`
}
