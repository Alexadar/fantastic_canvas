/**
 * Voice UI State Machine — orchestrates STT, TTS, AI connector.
 *
 * States:
 *   idle       → mic off, waiting for user action
 *   listening  → mic on, accumulating speech
 *   processing → transcript sent to AI, awaiting response
 *   speaking   → TTS playing AI response
 *
 * Transitions:
 *   idle       → listening   (user activates / auto after speaking)
 *   listening  → processing  (STT commits a prompt)
 *   processing → speaking    (AI response starts streaming)
 *   speaking   → listening   (barge-in: user talks over AI)
 *   speaking   → listening   (TTS finishes naturally)
 *   any        → idle        (user deactivates)
 */

import { createWebSpeechStt, type SttProvider } from './stt-provider'
import { createWebSpeechTts, type TtsProvider } from './tts-provider'
import { createAiConnector, type AiConnector } from './ai-connector'

export type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking'

export type PermissionState = 'unknown' | 'checking' | 'prompting' | 'granted' | 'denied' | 'unsupported'

export interface VoiceUiEvents {
  onStateChange: (state: VoiceState, announced: boolean) => void
  onPermission: (state: PermissionState) => void
  onInterim: (text: string) => void
  onTranscript: (text: string) => void
  onResponse: (text: string, done: boolean) => void
  onError: (error: string) => void
}

export interface VoiceUi {
  /** Activate the voice assistant (start listening). Checks permissions first. */
  activate(): Promise<void>
  /** Deactivate (go idle, stop everything) */
  deactivate(): void
  /** Toggle active/idle */
  toggle(): Promise<void>
  /** Feed a WS message from the backend */
  handleWsMessage(msg: any): void
  /** Current state */
  readonly state: VoiceState
  readonly isActive: boolean
  readonly permissionState: PermissionState
  /** Cleanup */
  destroy(): void
}

// State announcements — short spoken cues
const STATE_ANNOUNCEMENTS: Record<VoiceState, string> = {
  idle: '',
  listening: 'listening',
  processing: 'processing',
  speaking: '',  // no announcement when AI starts talking, that IS the speech
}

export function createVoiceUi(
  agentId: string,
  wsSend: (msg: any) => void,
  events: VoiceUiEvents,
): VoiceUi {
  let state: VoiceState = 'idle'
  let active = false
  let responseChunks: string[] = []
  let permState: PermissionState = 'unknown'

  // Sentence boundary detection for streaming TTS
  const SENTENCE_RE = /[.!?]\s+/

  function setState(next: VoiceState) {
    if (state === next) return
    state = next

    // Announce state change to user (spoken cue)
    const announcement = STATE_ANNOUNCEMENTS[next]
    if (announcement && tts) {
      tts.announce(announcement)
    }

    events.onStateChange(next, !!announcement)
  }

  function setPermission(next: PermissionState) {
    permState = next
    events.onPermission(next)
  }

  // ─── Permission checks ────────────────────────────────────
  // Probes mic permission without triggering the browser prompt.
  // Returns 'granted', 'denied', 'prompt' (ask needed), or 'unsupported'.
  async function probeMicPermission(): Promise<'granted' | 'denied' | 'prompt' | 'unsupported'> {
    // Check SpeechRecognition support
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    if (!SR) return 'unsupported'

    // navigator.permissions.query for microphone
    try {
      const result = await navigator.permissions.query({ name: 'microphone' as PermissionName })
      if (result.state === 'granted') return 'granted'
      if (result.state === 'denied') return 'denied'
      return 'prompt' // browser will ask
    } catch {
      // Firefox/Safari don't support permissions.query for microphone
      // Fall through to 'prompt' — getUserMedia will trigger the real prompt
      return 'prompt'
    }
  }

  // Forces the browser's mic permission dialog via getUserMedia.
  // This is the only way to get the prompt on first use.
  async function requestMicPermission(): Promise<boolean> {
    try {
      setPermission('prompting')
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      // Got permission — stop the stream immediately (STT manages its own)
      stream.getTracks().forEach(t => t.stop())
      setPermission('granted')
      return true
    } catch (err: any) {
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setPermission('denied')
      } else {
        setPermission('unsupported')
        events.onError(`Microphone error: ${err.message || err.name}`)
      }
      return false
    }
  }

  // Full permission gate: probe → prompt if needed → report result.
  // Returns true if we have mic access.
  async function ensureMicPermission(): Promise<boolean> {
    setPermission('checking')
    const probe = await probeMicPermission()

    if (probe === 'unsupported') {
      setPermission('unsupported')
      events.onError('Speech recognition not supported in this browser')
      return false
    }
    if (probe === 'denied') {
      setPermission('denied')
      return false
    }
    if (probe === 'granted') {
      setPermission('granted')
      return true
    }
    // probe === 'prompt' — force the browser dialog
    return await requestMicPermission()
  }

  // Warm up speechSynthesis (requires user gesture on some browsers)
  function warmUpTts() {
    const synth = window.speechSynthesis
    if (!synth) return
    // Speak an empty utterance to unlock TTS on user gesture
    const utt = new SpeechSynthesisUtterance('')
    utt.volume = 0
    synth.speak(utt)
  }

  // ─── STT ────────────────────────────────────────────────────
  const stt: SttProvider = createWebSpeechStt({
    onInterim(text) {
      events.onInterim(text)
    },
    onCommit(text) {
      events.onTranscript(text)
      setState('processing')
      ai.sendTranscript(text)
    },
    onSoundStart() {
      // Barge-in: if AI is speaking and user starts talking, interrupt
      if (state === 'speaking' && tts.isSpeaking) {
        tts.cancel()
        ai.sendInterrupt()
        setState('listening')
      }
    },
    onError(error) {
      events.onError(`STT: ${error}`)
    },
    onStateChange(_listening) {
      // STT auto-restart is handled internally
    },
  })

  // ─── TTS ────────────────────────────────────────────────────
  const tts: TtsProvider = createWebSpeechTts({
    onStart() {
      // Already in speaking state from AI response
    },
    onEnd() {
      // TTS finished naturally → back to listening if active
      if (active && state === 'speaking') {
        setState('listening')
        stt.start()
      }
    },
    onError(error) {
      events.onError(`TTS: ${error}`)
      if (active && state === 'speaking') {
        setState('listening')
        stt.start()
      }
    },
  })

  // ─── AI Connector ──────────────────────────────────────────
  const ai: AiConnector = createAiConnector(agentId, wsSend, {
    onResponseChunk(text, done) {
      if (state === 'processing') {
        setState('speaking')
      }

      if (done) {
        // Final: speak any remaining buffered text
        const remaining = responseChunks.join('')
        if (remaining.trim()) {
          tts.speak(remaining)
        }
        responseChunks = []
        events.onResponse(text, true)
      } else {
        // Streaming: buffer chunks, speak at sentence boundaries
        responseChunks.push(text)
        const combined = responseChunks.join('')
        const match = combined.match(SENTENCE_RE)
        if (match && match.index !== undefined) {
          const splitAt = match.index + match[0].length
          const sentence = combined.slice(0, splitAt)
          const remainder = combined.slice(splitAt)
          responseChunks = remainder ? [remainder] : []
          tts.speak(sentence)
        }
        events.onResponse(text, false)
      }
    },
    onStateChange(aiState) {
      // AI connector can signal state changes directly
      if (aiState === 'thinking' && state !== 'processing') {
        setState('processing')
      }
    },
    onError(error) {
      events.onError(`AI: ${error}`)
      // On error, go back to listening if active
      if (active) {
        setState('listening')
        stt.start()
      }
    },
  })

  return {
    async activate() {
      if (active) return

      // Gate on mic permission — force browser prompt if needed
      const allowed = await ensureMicPermission()
      if (!allowed) return

      // Warm up TTS on the same user gesture
      warmUpTts()

      active = true
      setState('listening')
      stt.start()
    },

    deactivate() {
      if (!active) return
      active = false
      stt.stop()
      tts.cancel()
      responseChunks = []
      setState('idle')
    },

    async toggle() {
      if (active) this.deactivate()
      else await this.activate()
    },

    handleWsMessage(msg: any) {
      ai.handleMessage(msg)
    },

    get state() { return state },
    get isActive() { return active },
    get permissionState() { return permState },

    destroy() {
      active = false
      stt.abort()
      tts.cancel()
    },
  }
}
