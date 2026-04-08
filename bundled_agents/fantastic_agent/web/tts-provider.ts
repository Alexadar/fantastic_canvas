/**
 * TTS Provider — Web Speech API with barge-in (interrupt) support.
 *
 * Key features:
 *   - Queued utterance playback
 *   - Instant cancel on interrupt (barge-in)
 *   - State announcements ("listening", "processing") spoken as short cues
 *   - Streaming: accepts chunks, queues them, speaks sequentially
 */

export interface TtsEvents {
  onStart: () => void
  onEnd: () => void
  onError: (error: string) => void
}

export interface TtsProvider {
  /** Speak a full or partial response. Queues if already speaking. */
  speak(text: string): void
  /** Speak a short state announcement (e.g. "listening"). Lower volume. */
  announce(text: string): void
  /** Immediately stop all speech (barge-in). */
  cancel(): void
  readonly isSpeaking: boolean
}

// ─── Tuning ─────────────────────────────────────────────────────
const ANNOUNCE_RATE = 1.3    // faster for state cues
const ANNOUNCE_VOLUME = 0.6  // softer for state cues
const RESPONSE_RATE = 1.0
const RESPONSE_VOLUME = 1.0

export function createWebSpeechTts(events: TtsEvents): TtsProvider {
  const synth = window.speechSynthesis
  if (!synth) {
    return {
      speak() { events.onError('speechSynthesis not supported') },
      announce() {},
      cancel() {},
      get isSpeaking() { return false },
    }
  }

  let speaking = false
  let voiceCache: SpeechSynthesisVoice | null = null

  function getVoice(): SpeechSynthesisVoice | null {
    if (voiceCache) return voiceCache
    const voices = synth.getVoices()
    // Prefer a natural-sounding English voice
    voiceCache =
      voices.find(v => v.lang.startsWith('en') && v.name.includes('Google')) ||
      voices.find(v => v.lang.startsWith('en') && v.localService) ||
      voices.find(v => v.lang.startsWith('en')) ||
      null
    return voiceCache
  }

  // Chrome bug: voices load async
  if (synth.onvoiceschanged !== undefined) {
    synth.onvoiceschanged = () => { voiceCache = null; getVoice() }
  }

  function makeUtterance(text: string, rate: number, volume: number): SpeechSynthesisUtterance {
    const utt = new SpeechSynthesisUtterance(text)
    utt.rate = rate
    utt.volume = volume
    const voice = getVoice()
    if (voice) utt.voice = voice
    return utt
  }

  return {
    speak(text: string) {
      if (!text.trim()) return
      const utt = makeUtterance(text, RESPONSE_RATE, RESPONSE_VOLUME)
      utt.onstart = () => {
        speaking = true
        events.onStart()
      }
      utt.onend = () => {
        // Only fire onEnd if nothing else is queued
        if (!synth.speaking && !synth.pending) {
          speaking = false
          events.onEnd()
        }
      }
      utt.onerror = (e) => {
        if (e.error === 'canceled' || e.error === 'interrupted') return
        speaking = false
        events.onError(e.error)
      }
      synth.speak(utt)
    },

    announce(text: string) {
      if (!text.trim()) return
      const utt = makeUtterance(text, ANNOUNCE_RATE, ANNOUNCE_VOLUME)
      // Announcements are fire-and-forget, no state tracking
      synth.speak(utt)
    },

    cancel() {
      synth.cancel()
      speaking = false
    },

    get isSpeaking() { return speaking || synth.speaking },
  }
}
