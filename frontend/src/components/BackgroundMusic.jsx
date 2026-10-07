import { useEffect, useRef, useState } from 'react'

const tracks = {
  home: '/music/home.mp3',
  'lecture-hall': '/music/lecture-hall.mp3',
  'private-tutor': '/music/private-tutor.mp3',
  'study-cafe': '/music/cafe.mp3',
}

export function BackgroundMusic({ track }) {
  const audioRef = useRef(null)
  const waitingForInteraction = useRef(false)
  const [isMuted, setIsMuted] = useState(false)

  useEffect(() => {
    const audio = new Audio()
    audio.loop = true
    audio.volume = 0.22
    audioRef.current = audio

    return () => {
      waitingForInteraction.current = false
      audio.pause()
      audio.removeAttribute('src')
      audioRef.current = null
    }
  }, [])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return

    const source = tracks[track] || tracks.home
    const nextSource = new URL(source, window.location.href).href
    if (audio.src !== nextSource) {
      audio.pause()
      audio.src = source
      audio.load()
    }

    if (isMuted) {
      audio.muted = true
      return
    }

    audio.muted = false
    audio.play().then(() => {
      waitingForInteraction.current = false
    }).catch(() => {
      waitingForInteraction.current = true
    })
  }, [track, isMuted])

  useEffect(() => {
    const resumeAfterInteraction = () => {
      const audio = audioRef.current
      if (!waitingForInteraction.current || !audio || isMuted) return

      audio.play().then(() => {
        waitingForInteraction.current = false
      }).catch(() => {})
    }

    window.addEventListener('pointerdown', resumeAfterInteraction)
    window.addEventListener('keydown', resumeAfterInteraction)
    return () => {
      window.removeEventListener('pointerdown', resumeAfterInteraction)
      window.removeEventListener('keydown', resumeAfterInteraction)
    }
  }, [isMuted])

  function toggleMuted() {
    setIsMuted((muted) => !muted)
  }

  return (
    <button
      className="music-toggle"
      type="button"
      aria-label={isMuted ? 'Unmute background music' : 'Mute background music'}
      aria-pressed={isMuted}
      onClick={toggleMuted}
    >
      <svg className="music-toggle-icon" viewBox="0 0 24 24" aria-hidden="true" shapeRendering="crispEdges">
        <path d="M3 9h4l5-4v14l-5-4H3z" fill="currentColor" />
        {!isMuted && <path d="M15 8h2v2h2v4h-2v2h-2v-2h2v-4h-2z" fill="currentColor" />}
        {isMuted && <path d="M15 8h2v2h2v2h-2v2h-2v2h-2v-2h2v-2h-2v-2h2z" fill="currentColor" />}
      </svg>
    </button>
  )
}
