import { registry } from '@bundles/canvas/web/src/plugins/registry'
import type { CanvasPlugin } from '@bundles/canvas/web/src/plugins/types'
import type { WSMessage } from '@bundles/canvas/web/src/types'
import { createVoiceUi, type VoiceState } from './web/voice-ui'
import { createChatUi } from './web/chat-ui'

type AgentMode = 'voice' | 'chat'

// ─── Shared style injection (once) ──────────────────────────────
const STYLE_ID = 'fantastic-agent-styles'

function injectStyles() {
  if (document.getElementById(STYLE_ID)) return
  const style = document.createElement('style')
  style.id = STYLE_ID
  style.textContent = `
    /* ── Voice orb ── */
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

    /* ── Chat UI ── */
    .fa-chat-container {
      display: flex;
      flex-direction: column;
      width: 100%;
      height: 100%;
      background: #1a1a2e;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    .fa-chat-messages {
      flex: 1;
      overflow-y: auto;
      padding: 8px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    .fa-chat-msg {
      max-width: 85%;
      padding: 6px 10px;
      border-radius: 10px;
      font-size: 13px;
      line-height: 1.4;
      word-wrap: break-word;
    }

    .fa-chat-msg.user {
      align-self: flex-end;
      background: #3a3a6a;
      color: #e0e0ff;
      border-bottom-right-radius: 2px;
    }

    .fa-chat-msg.assistant {
      align-self: flex-start;
      background: #2a2a3e;
      color: #d0d0e8;
      border-bottom-left-radius: 2px;
    }

    .fa-chat-msg .fa-chat-mode-tag {
      font-size: 9px;
      opacity: 0.5;
      margin-left: 6px;
    }

    .fa-chat-input-row {
      display: flex;
      padding: 6px;
      gap: 4px;
      border-top: 1px solid rgba(255,255,255,0.1);
    }

    .fa-chat-input {
      flex: 1;
      background: #2a2a3e;
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 6px;
      padding: 6px 10px;
      color: #e0e0ff;
      font-size: 13px;
      outline: none;
    }

    .fa-chat-input:focus {
      border-color: rgba(100, 150, 255, 0.5);
    }

    .fa-chat-send {
      background: #4a3a8a;
      border: none;
      border-radius: 6px;
      color: white;
      padding: 6px 12px;
      cursor: pointer;
      font-size: 13px;
    }

    .fa-chat-send:hover {
      background: #5a4a9a;
    }

    /* ── Mode toggle (header) ── */
    .fa-mode-toggle {
      display: inline-flex;
      align-items: center;
      gap: 2px;
      background: rgba(255,255,255,0.08);
      border-radius: 4px;
      padding: 2px;
      cursor: pointer;
      border: none;
    }

    .fa-mode-btn {
      background: none;
      border: none;
      color: rgba(255,255,255,0.4);
      font-size: 14px;
      padding: 2px 6px;
      border-radius: 3px;
      cursor: pointer;
      transition: all 0.15s;
    }

    .fa-mode-btn.active {
      background: rgba(255,255,255,0.15);
      color: rgba(255,255,255,0.9);
    }
  `
  document.head.appendChild(style)
}

// ─── State icons ──────────────────────────────────────────────
const STATE_ICONS: Record<VoiceState, string> = {
  idle: '\u{1F3A4}',        // microphone
  listening: '\u{1F7E2}',   // green circle
  processing: '\u{23F3}',   // hourglass
  speaking: '\u{1F50A}',    // speaker
}

const STATE_LABELS: Record<VoiceState, string> = {
  idle: 'tap to start',
  listening: 'listening',
  processing: 'processing',
  speaking: 'speaking',
}

// ─── Plugin ───────────────────────────────────────────────────
export const fantasticAgentPlugin: CanvasPlugin = {
  name: 'fantastic_agent',
  accentColor: '#4a3a8a',

  matchAgent: (agent) => agent.bundle === 'fantastic_agent',

  // Ctrl/Cmd+dblclick on canvas creates AI agent
  injectCanvas: (dom, ctx) => {
    const handler = (e: MouseEvent) => {
      if (!e.shiftKey) return  // only Shift+dblclick
      if ((e.target as HTMLElement).closest('.agent-wrapper')) return
      const { x, y } = ctx.screenToCanvas(e)
      ctx.send({ type: 'create_agent', template: 'fantastic_agent', options: { x, y } })
    }
    dom.addEventListener('dblclick', handler)
    return () => dom.removeEventListener('dblclick', handler)
  },

  injectHeader: (dom, ctx) => {
    const toggle = document.createElement('div')
    toggle.className = 'fa-mode-toggle'

    const voiceBtn = document.createElement('button')
    voiceBtn.className = 'fa-mode-btn active'
    voiceBtn.textContent = '\u{1F3A4}'  // microphone
    voiceBtn.title = 'Voice mode'

    const chatBtn = document.createElement('button')
    chatBtn.className = 'fa-mode-btn'
    chatBtn.textContent = '\u{1F4AC}'  // speech bubble
    chatBtn.title = 'Chat mode'

    toggle.appendChild(voiceBtn)
    toggle.appendChild(chatBtn)
    dom.appendChild(toggle)

    // Mode switch dispatched via custom event on the agent's DOM
    voiceBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      voiceBtn.classList.add('active')
      chatBtn.classList.remove('active')
      dom.dispatchEvent(new CustomEvent('fa-mode-change', { detail: 'voice', bubbles: true }))
    })

    chatBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      chatBtn.classList.add('active')
      voiceBtn.classList.remove('active')
      dom.dispatchEvent(new CustomEvent('fa-mode-change', { detail: 'chat', bubbles: true }))
    })

    return () => { toggle.remove() }
  },

  injectAgent: (dom, ctx) => {
    injectStyles()

    let currentMode: AgentMode = 'voice'
    const agentId = ctx.agent.id

    // ── Voice DOM ──
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

    dom.appendChild(orb)

    // ── Chat DOM ──
    const chatContainer = document.createElement('div')
    chatContainer.className = 'fa-chat-container'
    chatContainer.style.display = 'none'
    dom.appendChild(chatContainer)

    // ── Voice UI controller ──
    const voiceUi = createVoiceUi(agentId, ctx.send, {
      onStateChange(state: VoiceState) {
        orb.dataset.state = state
        icon.textContent = STATE_ICONS[state]
        label.textContent = STATE_LABELS[state]
        if (state === 'listening') {
          transcript.textContent = ''
        }
      },
      onInterim(text: string) {
        transcript.textContent = text.length > 60 ? '...' + text.slice(-57) : text
      },
      onTranscript(text: string) {
        transcript.textContent = text.length > 60 ? '...' + text.slice(-57) : text
      },
      onResponse(text: string, done: boolean) {
        if (done) {
          transcript.textContent = text.length > 60 ? text.slice(0, 57) + '...' : text
        }
      },
      onError(error: string) {
        transcript.textContent = error
        setTimeout(() => {
          if (transcript.textContent === error) transcript.textContent = ''
        }, 3000)
      },
    })

    // ── Chat UI controller ──
    const chatUi = createChatUi(agentId, ctx.send, {
      onError(error: string) {
        // Could show in chat, for now just log
        console.warn('[fantastic_agent] chat error:', error)
      },
    })
    chatContainer.appendChild(chatUi.dom)

    // Load chat history on init
    ctx.send({ type: 'chat_history', agent_id: agentId })

    // ── Click to toggle voice ──
    orb.addEventListener('click', (e) => {
      e.stopPropagation()
      voiceUi.toggle()
    })

    // ── Mode switching ──
    function setMode(mode: AgentMode) {
      if (mode === currentMode) return
      currentMode = mode
      if (mode === 'voice') {
        orb.style.display = ''
        chatContainer.style.display = 'none'
      } else {
        // Deactivate voice when switching to chat
        voiceUi.deactivate()
        orb.style.display = 'none'
        chatContainer.style.display = ''
        chatUi.focus()
      }
    }

    // Listen for mode toggle from header
    const modeHandler = (e: Event) => {
      const mode = (e as CustomEvent).detail as AgentMode
      setMode(mode)
    }
    // Listen on document for bubbled events from header
    document.addEventListener('fa-mode-change', modeHandler)

    // ── WS subscription ──
    const unsub = ctx.subscribe((msg: WSMessage) => {
      // Voice mic owner — exclusivity
      if (msg.type === 'voice_mic_owner') {
        if (msg.agent_id === agentId) {
          // We got the mic — activate voice
          if (currentMode === 'voice' && !voiceUi.isActive) {
            voiceUi.activateLocal()
          }
        } else {
          // Another agent got the mic (or null) — deactivate
          if (voiceUi.isActive) {
            voiceUi.deactivate()
          }
        }
        return
      }

      // Chat history response
      if (msg.type === 'chat_history_response' && msg.agent_id === agentId) {
        chatUi.loadHistory((msg.messages || []) as Array<{ role: string; text: string; ts?: number; mode?: string }>)
        return
      }

      // Voice response also goes to chat UI for history display
      if (msg.agent_id === agentId && msg.type === 'voice_response' && msg.done) {
        chatUi.appendMessage('assistant', (msg.text || '') as string)
      }

      // Forward to voice UI
      voiceUi.handleWsMessage(msg)
    })

    return () => {
      voiceUi.destroy()
      chatUi.destroy()
      unsub()
      document.removeEventListener('fa-mode-change', modeHandler)
      orb.remove()
      chatContainer.remove()
    }
  },
}

registry.register(fantasticAgentPlugin)
