/**
 * STT Provider — Web Speech API with intelligent prompt detection.
 *
 * "Intelligent" means: we don't fire on every silence gap. We accumulate
 * interim results and only commit when the user has *finished a thought*:
 *   1. Final result from recognizer (browser decided sentence is done), OR
 *   2. Silence after speech for SILENCE_COMMIT_MS with accumulated text, OR
 *   3. No new interim results for IDLE_COMMIT_MS (user paused mid-word).
 *
 * This avoids sending half-sentences to the AI backend.
 */

export interface SttEvents {
  /** Interim (partial) transcript — for UI display */
  onInterim: (text: string) => void
  /** Final committed prompt — ready to send to AI */
  onCommit: (text: string) => void
  /** User started making sound (for barge-in detection) */
  onSoundStart: () => void
  /** STT error */
  onError: (error: string) => void
  /** STT state change */
  onStateChange: (listening: boolean) => void
}

export interface SttProvider {
  start(): void
  stop(): void
  abort(): void
  readonly isListening: boolean
}

// ─── Tuning knobs ────────────────────────────────────────────────
const SILENCE_COMMIT_MS = 1200   // silence after speech → commit
const IDLE_COMMIT_MS = 2000      // no interim updates → commit
const MIN_COMMIT_LENGTH = 2      // ignore ultra-short noise commits

export function createWebSpeechStt(events: SttEvents): SttProvider {
  const SpeechRecognition =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition

  if (!SpeechRecognition) {
    return {
      start() { events.onError('SpeechRecognition not supported in this browser') },
      stop() {},
      abort() {},
      get isListening() { return false },
    }
  }

  const recognition = new SpeechRecognition()
  recognition.continuous = true
  recognition.interimResults = true
  recognition.lang = 'en-US'

  let listening = false
  let buffer = ''            // accumulated final fragments
  let lastInterim = ''       // latest interim text
  let silenceTimer: ReturnType<typeof setTimeout> | null = null
  let idleTimer: ReturnType<typeof setTimeout> | null = null
  let shouldRestart = false

  function clearTimers() {
    if (silenceTimer) { clearTimeout(silenceTimer); silenceTimer = null }
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
  }

  function commit() {
    clearTimers()
    const text = (buffer + ' ' + lastInterim).trim()
    buffer = ''
    lastInterim = ''
    if (text.length >= MIN_COMMIT_LENGTH) {
      events.onCommit(text)
    }
  }

  function resetIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      if ((buffer + lastInterim).trim().length >= MIN_COMMIT_LENGTH) {
        commit()
      }
    }, IDLE_COMMIT_MS)
  }

  recognition.onresult = (e: any) => {
    let interim = ''
    let finalText = ''

    for (let i = e.resultIndex; i < e.results.length; i++) {
      const transcript = e.results[i][0].transcript
      if (e.results[i].isFinal) {
        finalText += transcript
      } else {
        interim += transcript
      }
    }

    if (finalText) {
      buffer += (buffer ? ' ' : '') + finalText.trim()
      lastInterim = ''
      // Browser said this chunk is final — start silence timer
      clearTimers()
      silenceTimer = setTimeout(commit, SILENCE_COMMIT_MS)
    }

    if (interim) {
      lastInterim = interim
      events.onInterim((buffer + ' ' + interim).trim())
      resetIdleTimer()
    }
  }

  recognition.onsoundstart = () => {
    events.onSoundStart()
  }

  recognition.onend = () => {
    // If we still have buffered text, commit it
    if ((buffer + lastInterim).trim().length >= MIN_COMMIT_LENGTH) {
      commit()
    }
    listening = false
    events.onStateChange(false)
    // Auto-restart if we didn't explicitly stop
    if (shouldRestart) {
      try { recognition.start() } catch (_) {}
    }
  }

  recognition.onerror = (e: any) => {
    if (e.error === 'no-speech' || e.error === 'aborted') return
    events.onError(e.error)
  }

  recognition.onstart = () => {
    listening = true
    events.onStateChange(true)
  }

  return {
    start() {
      shouldRestart = true
      if (!listening) {
        try { recognition.start() } catch (_) {}
      }
    },
    stop() {
      shouldRestart = false
      clearTimers()
      if ((buffer + lastInterim).trim().length >= MIN_COMMIT_LENGTH) {
        commit()
      }
      try { recognition.stop() } catch (_) {}
    },
    abort() {
      shouldRestart = false
      clearTimers()
      buffer = ''
      lastInterim = ''
      try { recognition.abort() } catch (_) {}
    },
    get isListening() { return listening },
  }
}
