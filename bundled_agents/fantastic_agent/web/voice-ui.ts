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
 *
 * Mic exclusivity:
 *   activate()      → sends voice_claim_mic, waits for voice_mic_owner broadcast
 *   activateLocal() → directly starts STT (called when mic_owner confirms us)
 *   deactivate()    → sends voice_release_mic, stops STT/TTS
 */

import { createWebSpeechStt, type SttProvider } from './stt-provider'
import { createWebSpeechTts, type TtsProvider } from './tts-provider'
import { createAiConnector, type AiConnector } from './ai-connector'

export type VoiceState = 'idle' | 'listening' | 'processing' | 'speaking'

export interface VoiceUiEvents {
  onStateChange: (state: VoiceState, announced: boolean) => void
  onInterim: (text: string) => void
  onTranscript: (text: string) => void
  onResponse: (text: string, done: boolean) => void
  onError: (error: string) => void
}

export interface VoiceUi {
  /** Activate — claims mic via WS (other agents will be deactivated) */
  activate(): void
  /** Activate locally without claiming mic (called by plugin on mic_owner confirmation) */
  activateLocal(): void
  /** Deactivate (go idle, stop everything, release mic) */
  deactivate(): void
  /** Toggle active/idle */
  toggle(): void
  /** Feed a WS message from the backend */
  handleWsMessage(msg: any): void
  /** Current state */
  readonly state: VoiceState
  readonly isActive: boolean
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
    activate() {
      if (active) return
      // Claim mic via WS — actual activation happens when voice_mic_owner comes back
      wsSend({ type: 'voice_claim_mic', agent_id: agentId })
    },

    activateLocal() {
      // Called by plugin when voice_mic_owner confirms this agent
      if (active) return
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
      // Release mic
      wsSend({ type: 'voice_release_mic', agent_id: agentId })
    },

    toggle() {
      if (active) this.deactivate()
      else this.activate()
    },

    handleWsMessage(msg: any) {
      ai.handleMessage(msg)
    },

    get state() { return state },
    get isActive() { return active },

    destroy() {
      active = false
      stt.abort()
      tts.cancel()
    },
  }
}
