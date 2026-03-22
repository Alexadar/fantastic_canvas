import { registry } from '@bundles/canvas/web/src/plugins/registry'
import type { CanvasPlugin } from '@bundles/canvas/web/src/plugins/types'
import type { WSMessage } from '@bundles/canvas/web/src/types'
import { createVoiceUi, type VoiceState, type PermissionState } from './web/voice-ui'

// ─── Orb CSS (injected once) ──────────────────────────────────
const STYLE_ID = 'voice-assistant-styles'

function injectStyles() {
  if (document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = `
    .voice-orb {
      width: 100%;
      height: 100%;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      border-radius: 50%;
      cursor: pointer;
      user-select: none;
      position: relative;
      overflow: hidden;
      background: radial-gradient(circle at 40% 40%, #2a2a3e, #111128);
      transition: box-shadow 0.3s ease;
    }

    .voice-orb[data-state="idle"] {
      box-shadow: 0 0 20px rgba(100, 100, 180, 0.3);
    }

    .voice-orb[data-state="listening"] {
      box-shadow: 0 0 30px rgba(80, 200, 120, 0.5), 0 0 60px rgba(80, 200, 120, 0.2);
      animation: voice-pulse-listen 2s ease-in-out infinite;
    }

    .voice-orb[data-state="processing"] {
      box-shadow: 0 0 30px rgba(255, 180, 50, 0.5), 0 0 60px rgba(255, 180, 50, 0.2);
      animation: voice-pulse-process 1s ease-in-out infinite;
    }

    .voice-orb[data-state="speaking"] {
      box-shadow: 0 0 30px rgba(100, 150, 255, 0.5), 0 0 60px rgba(100, 150, 255, 0.2);
      animation: voice-pulse-speak 0.8s ease-in-out infinite;
    }

    .voice-orb-icon {
      font-size: 48px;
      z-index: 1;
      filter: drop-shadow(0 0 8px rgba(255,255,255,0.3));
      transition: transform 0.2s ease;
    }

    .voice-orb[data-state="listening"] .voice-orb-icon { transform: scale(1.1); }
    .voice-orb[data-state="processing"] .voice-orb-icon { animation: voice-spin 2s linear infinite; }

    .voice-orb-label {
      margin-top: 8px;
      font-size: 12px;
      font-family: monospace;
      color: rgba(255, 255, 255, 0.7);
      text-transform: uppercase;
      letter-spacing: 2px;
      z-index: 1;
    }

    .voice-orb-transcript {
      position: absolute;
      bottom: 12px;
      left: 12px;
      right: 12px;
      font-size: 11px;
      font-family: monospace;
      color: rgba(255, 255, 255, 0.5);
      text-align: center;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      z-index: 1;
    }

    /* Ring ripple behind orb */
    .voice-orb-ring {
      position: absolute;
      width: 80%;
      height: 80%;
      border-radius: 50%;
      border: 2px solid rgba(255, 255, 255, 0.1);
      pointer-events: none;
    }

    .voice-orb[data-state="speaking"] .voice-orb-ring {
      animation: voice-ring-out 1.5s ease-out infinite;
    }

    .voice-orb[data-state="listening"] .voice-orb-ring {
      animation: voice-ring-in 2s ease-in-out infinite;
    }

    @keyframes voice-pulse-listen {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.03); }
    }

    @keyframes voice-pulse-process {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.02); }
    }

    @keyframes voice-pulse-speak {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.04); }
    }

    @keyframes voice-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }

    @keyframes voice-ring-out {
      0% { transform: scale(1); opacity: 0.4; }
      100% { transform: scale(1.5); opacity: 0; }
    }

    @keyframes voice-ring-in {
      0%, 100% { transform: scale(0.9); opacity: 0.2; }
      50% { transform: scale(1.1); opacity: 0.4; }
    }

    /* Permission overlay */
    .voice-perm-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.85);
      border-radius: 50%;
      z-index: 10;
      padding: 16px;
      text-align: center;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.3s ease;
    }

    .voice-perm-overlay.visible {
      opacity: 1;
      pointer-events: auto;
    }

    .voice-perm-overlay-icon {
      font-size: 36px;
      margin-bottom: 8px;
    }

    .voice-perm-overlay-text {
      font-size: 11px;
      font-family: monospace;
      color: rgba(255, 255, 255, 0.8);
      line-height: 1.4;
      max-width: 90%;
    }

    .voice-perm-overlay[data-perm="checking"] .voice-perm-overlay-icon {
      animation: voice-spin 1.5s linear infinite;
    }

    .voice-perm-overlay[data-perm="denied"] {
      background: rgba(80, 0, 0, 0.9);
    }

    .voice-perm-overlay[data-perm="unsupported"] {
      background: rgba(60, 40, 0, 0.9);
    }
  `
  document.head.appendChild(style)
}

// ─── State icons ──────────────────────────────────────────────
const STATE_ICONS: Record<VoiceState, string> = {
  idle: '\u{1F3A4}',        // 🎤
  listening: '\u{1F7E2}',   // 🟢
  processing: '\u{23F3}',   // ⏳
  speaking: '\u{1F50A}',    // 🔊
}

const STATE_LABELS: Record<VoiceState, string> = {
  idle: 'tap to start',
  listening: 'listening',
  processing: 'processing',
  speaking: 'speaking',
}

// ─── Plugin ───────────────────────────────────────────────────
export const voiceAssistantPlugin: CanvasPlugin = {
  name: 'voice_assistant',
  accentColor: '#4a3a8a',

  matchAgent: (agent) => agent.bundle === 'voice_assistant',

  injectAgent: (dom, ctx) => {
    injectStyles()

    // Build orb DOM
    const orb = document.createElement('div')
    orb.className = 'voice-orb'
    orb.dataset.state = 'idle'

    const ring = document.createElement('div')
    ring.className = 'voice-orb-ring'
    orb.appendChild(ring)

    const icon = document.createElement('div')
    icon.className = 'voice-orb-icon'
    icon.textContent = STATE_ICONS.idle
    orb.appendChild(icon)

    const label = document.createElement('div')
    label.className = 'voice-orb-label'
    label.textContent = STATE_LABELS.idle
    orb.appendChild(label)

    const transcript = document.createElement('div')
    transcript.className = 'voice-orb-transcript'
    transcript.textContent = ''
    orb.appendChild(transcript)

    // Permission overlay
    const permOverlay = document.createElement('div')
    permOverlay.className = 'voice-perm-overlay'
    const permIcon = document.createElement('div')
    permIcon.className = 'voice-perm-overlay-icon'
    const permText = document.createElement('div')
    permText.className = 'voice-perm-overlay-text'
    permOverlay.appendChild(permIcon)
    permOverlay.appendChild(permText)
    orb.appendChild(permOverlay)

    dom.appendChild(orb)

    // Permission UI state
    const PERM_UI: Record<PermissionState, { icon: string; text: string; visible: boolean }> = {
      unknown:     { icon: '',   text: '',                                        visible: false },
      checking:    { icon: '\u{1F50D}', text: 'Checking mic access...',           visible: true },
      prompting:   { icon: '\u{1F3A4}', text: 'Allow microphone access\nin the browser prompt above', visible: true },
      granted:     { icon: '\u{2705}',  text: 'Mic access granted',              visible: false },
      denied:      { icon: '\u{1F6AB}', text: 'Mic access denied.\nAllow in browser settings\nthen tap again.', visible: true },
      unsupported: { icon: '\u{26A0}\u{FE0F}',  text: 'Speech recognition\nnot supported in\nthis browser.', visible: true },
    }

    let permDismissTimer: ReturnType<typeof setTimeout> | null = null

    // Create voice UI controller
    const voiceUi = createVoiceUi(ctx.agent.id, ctx.send, {
      onPermission(perm: PermissionState) {
        const ui = PERM_UI[perm]
        permOverlay.dataset.perm = perm
        permIcon.textContent = ui.icon
        permText.textContent = ui.text

        if (permDismissTimer) { clearTimeout(permDismissTimer); permDismissTimer = null }

        if (ui.visible) {
          permOverlay.classList.add('visible')
          // Auto-dismiss denied/unsupported after 5s
          if (perm === 'denied' || perm === 'unsupported') {
            permDismissTimer = setTimeout(() => {
              permOverlay.classList.remove('visible')
            }, 5000)
          }
        } else {
          // Brief flash for granted, then hide
          if (perm === 'granted') {
            permOverlay.classList.add('visible')
            permIcon.textContent = '\u{2705}'
            permText.textContent = 'Mic access granted'
            permDismissTimer = setTimeout(() => {
              permOverlay.classList.remove('visible')
            }, 800)
          } else {
            permOverlay.classList.remove('visible')
          }
        }
      },
      onStateChange(state: VoiceState) {
        orb.dataset.state = state
        icon.textContent = STATE_ICONS[state]
        label.textContent = STATE_LABELS[state]

        if (state === 'listening') {
          transcript.textContent = ''
        }
      },
      onInterim(text: string) {
        transcript.textContent = text.length > 60
          ? '...' + text.slice(-57)
          : text
      },
      onTranscript(text: string) {
        transcript.textContent = text.length > 60
          ? '...' + text.slice(-57)
          : text
      },
      onResponse(text: string, done: boolean) {
        if (done) {
          transcript.textContent = text.length > 60
            ? text.slice(0, 57) + '...'
            : text
        }
      },
      onError(error: string) {
        transcript.textContent = error
        setTimeout(() => {
          if (transcript.textContent === error) {
            transcript.textContent = ''
          }
        }, 3000)
      },
    })

    // Click to toggle (async — may trigger permission prompt)
    orb.addEventListener('click', (e) => {
      e.stopPropagation()
      voiceUi.toggle().catch(() => {})
    })

    // Subscribe to WS messages for this agent
    const unsub = ctx.subscribe((msg: WSMessage) => {
      voiceUi.handleWsMessage(msg)
    })

    return () => {
      voiceUi.destroy()
      unsub()
      orb.remove()
    }
  },
}

registry.register(voiceAssistantPlugin)
