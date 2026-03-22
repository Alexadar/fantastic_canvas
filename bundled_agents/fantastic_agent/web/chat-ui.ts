/**
 * Chat UI — text-based chat interface for fantastic agent.
 *
 * Reuses the same backend handlers (voice_transcript) with mode="chat".
 * Messages are persisted to chat.json via the backend.
 */

export interface ChatUiEvents {
  onError: (error: string) => void
}

export interface ChatUi {
  /** The root DOM element to mount */
  readonly dom: HTMLElement
  /** Load history from backend response */
  loadHistory(messages: Array<{ role: string; text: string; ts?: number; mode?: string }>): void
  /** Append a single message to the display (used for live responses) */
  appendMessage(role: string, text: string, mode?: string): void
  /** Focus the input field */
  focus(): void
  /** Cleanup */
  destroy(): void
}

export function createChatUi(
  agentId: string,
  wsSend: (msg: any) => void,
  events: ChatUiEvents,
): ChatUi {
  // ── Build DOM ──
  const container = document.createElement('div')
  container.style.cssText = 'display:flex;flex-direction:column;width:100%;height:100%;'

  const messageList = document.createElement('div')
  messageList.className = 'fa-chat-messages'
  container.appendChild(messageList)

  const inputRow = document.createElement('div')
  inputRow.className = 'fa-chat-input-row'

  const input = document.createElement('input')
  input.className = 'fa-chat-input'
  input.type = 'text'
  input.placeholder = 'Type a message...'

  const sendBtn = document.createElement('button')
  sendBtn.className = 'fa-chat-send'
  sendBtn.textContent = 'Send'

  inputRow.appendChild(input)
  inputRow.appendChild(sendBtn)
  container.appendChild(inputRow)

  let historyLoaded = false

  // ── Helpers ──
  function addMessageEl(role: string, text: string, mode?: string) {
    const msg = document.createElement('div')
    msg.className = `fa-chat-msg ${role}`
    msg.textContent = text
    if (mode) {
      const tag = document.createElement('span')
      tag.className = 'fa-chat-mode-tag'
      tag.textContent = mode
      msg.appendChild(tag)
    }
    messageList.appendChild(msg)
    messageList.scrollTop = messageList.scrollHeight
  }

  function sendMessage() {
    const text = input.value.trim()
    if (!text) return
    input.value = ''
    addMessageEl('user', text, 'chat')
    wsSend({
      type: 'voice_transcript',
      agent_id: agentId,
      text,
      is_final: true,
      mode: 'chat',
    })
  }

  // ── Events ──
  sendBtn.addEventListener('click', (e) => {
    e.stopPropagation()
    sendMessage()
  })

  input.addEventListener('keydown', (e) => {
    e.stopPropagation()
    if (e.key === 'Enter') {
      e.preventDefault()
      sendMessage()
    }
  })

  // Stop click propagation on input so canvas doesn't handle it
  input.addEventListener('click', (e) => e.stopPropagation())
  input.addEventListener('mousedown', (e) => e.stopPropagation())

  return {
    dom: container,

    loadHistory(messages) {
      if (historyLoaded) return
      historyLoaded = true
      messageList.innerHTML = ''
      for (const msg of messages) {
        addMessageEl(msg.role, msg.text, msg.mode)
      }
    },

    appendMessage(role: string, text: string, mode?: string) {
      addMessageEl(role, text, mode)
    },

    focus() {
      setTimeout(() => input.focus(), 50)
    },

    destroy() {
      container.remove()
    },
  }
}
