export const pregeneratedSpeech = {
  welcome: {
    fileName: 'welcome.wav',
    text: {
      'lecture-hall':
        "Welcome. I am Professor Regina. Let us begin by looking carefully at today's lecture.",
      'private-tutor':
        'Hi, I am Regina. We will take this one step at a time.',
      'study-cafe':
        "Hey, I am Regina. Let's go through this together and make it make sense.",
    },
  },
  handRaisePrompt: {
    fileName: 'what-would-you-like-to-ask.wav',
    text: {
      'lecture-hall': 'Yes, go ahead. What question would you like to raise?',
      'private-tutor': 'Of course. What are you wondering about?',
      'study-cafe': 'Yeah, tell me what part feels confusing.',
    },
  },
  thinking: {
    fileName: 'let-me-think.wav',
    text: {
      'lecture-hall': 'Let me consider that for a moment.',
      'private-tutor': 'Let me think that through for a second.',
      'study-cafe': 'Hmm, give me a second to think about that.',
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
