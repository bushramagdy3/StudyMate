import { useEffect, useRef, useState } from 'react'
import handIcon from '../assets/generated-icons/hand-transparent.png'
import loadingIcon from '../assets/generated-icons/outline-loading.gif'
import voiceMicIcon from '../assets/generated-icons/voice-mic.png'
import voiceStopIcon from '../assets/generated-icons/voice-stop.png'
import './VoiceRecorder.css'

const placeholders = {
  answer: 'Type your answer...',
  continue: 'Type your question or share a thought...',
  nothing: 'Choose a topic from the outline...',
  question: 'Type your question...',
}

export function MessageBar({
  awaiting,
  canRaiseHand = false,
  disabled = false,
  voiceDisabled = false,
  voiceProcessing = false,
  onRaiseHand,
  onSendMessage,
  onVoiceRecording,
  onVoiceError,
}) {
  const [message, setMessage] = useState('')
  const [isRecording, setIsRecording] = useState(false)
  const recorderRef = useRef(null)
  const streamRef = useRef(null)
  const chunksRef = useRef([])
  const disposedRef = useRef(false)

  const stopStream = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
  }

  const stopRecording = () => {
    if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
  }

  useEffect(() => {
    // React Strict Mode runs an extra setup/cleanup cycle in development.
    // Resetting this flag here keeps a real microphone stream from being
    // discarded after that development-only cleanup pass.
    disposedRef.current = false

    return () => {
      disposedRef.current = true
      recorderRef.current?.stop()
      stopStream()
    }
  }, [])

  const startRecording = async () => {
    if (disabled || voiceDisabled || voiceProcessing || !['answer', 'question'].includes(awaiting)) return
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      onVoiceError?.(new Error('Voice recording is not supported in this browser. Type your response instead.'))
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (disposedRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      const mimeType = MediaRecorder.isTypeSupported?.('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : ''
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
      streamRef.current = stream
      recorderRef.current = recorder
      chunksRef.current = []
      recorder.ondataavailable = ({ data }) => {
        if (data.size) chunksRef.current.push(data)
      }
      recorder.onstop = async () => {
        const recording = new Blob(chunksRef.current, { type: recorder.mimeType || mimeType || 'audio/webm' })
        recorderRef.current = null
        stopStream()
        setIsRecording(false)
        if (!disposedRef.current && recording.size) {
          const transcript = await onVoiceRecording?.(recording)
          if (!disposedRef.current && transcript) setMessage(transcript)
        }
      }
      recorder.start()
      setIsRecording(true)
    } catch (error) {
      stopStream()
      onVoiceError?.(new Error(error?.name === 'NotAllowedError'
        ? 'Microphone access was denied. Type your response instead.'
        : 'Could not start voice recording. Type your response instead.'))
    }
  }
  const canSend =
    !disabled &&
    !isRecording &&
    !voiceProcessing &&
    ['answer', 'question'].includes(awaiting) &&
    Boolean(message.trim())
  const isHandRaised = awaiting === 'question' && canRaiseHand

  function sendMessage() {
    const text = message.trim()

    if (!text || disabled || isRecording || voiceProcessing) {
      return
    }

    onSendMessage(text)
    setMessage('')
  }

  return (
    <section className="message-bar" aria-label="Ask a question">
      <div className="voice-input-shell">
        <input
          className="message-input"
          disabled={disabled || isRecording || voiceProcessing || awaiting === 'continue' || awaiting === 'nothing'}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && canSend) {
              sendMessage()
            }
          }}
          placeholder={disabled ? 'Thinking...' : placeholders[awaiting] || placeholders.continue}
          type="text"
          value={message}
        />
        {(isRecording || voiceProcessing) && (
          <div className="voice-recording-display" role="status" aria-live="polite">
            {voiceProcessing && <img src={loadingIcon} alt="" />}
            <span>{isRecording ? 'Listening... tap stop when you finish' : 'Transcribing your answer...'}</span>
          </div>
        )}
      </div>
      <button
        className={`voice-control${isRecording ? ' voice-control--recording' : ''}${voiceProcessing ? ' voice-control--processing' : ''}`}
        type="button"
        disabled={isRecording ? false : disabled || voiceDisabled || voiceProcessing || !['answer', 'question'].includes(awaiting)}
        onClick={isRecording ? stopRecording : startRecording}
        aria-label={isRecording ? 'Stop recording' : voiceDisabled ? 'Voice input is unavailable' : 'Record an answer or question'}
        title={isRecording ? 'Stop recording' : voiceDisabled ? 'Voice input is unavailable' : 'Record an answer or question'}
      >
        <img
          className={`voice-control__icon${voiceProcessing ? ' is-loading' : ''}`}
          src={voiceProcessing ? loadingIcon : isRecording ? voiceStopIcon : voiceMicIcon}
          alt=""
          aria-hidden="true"
        />
      </button>

      <button
        className="message-send"
        disabled={!canSend}
        type="button"
        onClick={sendMessage}
      >
        Send
      </button>

      <button
        className={isHandRaised ? 'raise-hand raised' : 'raise-hand'}
        disabled={disabled || isRecording || voiceProcessing || !canRaiseHand}
        type="button"
        aria-pressed={isHandRaised}
        onClick={onRaiseHand}
      >
        <img src={handIcon} alt="" />
        <span>Raise Hand</span>
      </button>
    </section>
  )
}
