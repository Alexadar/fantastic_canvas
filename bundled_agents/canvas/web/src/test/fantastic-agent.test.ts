/**
 * Tests for fantastic_agent frontend modules:
 *   - ai-connector: WS message handling, mode field
 *   - chat-ui: DOM construction, message rendering, input handling
 *   - voice-ui: state machine, mic claim/release
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createAiConnector } from '@bundles/fantastic_agent/web/ai-connector'
import { createChatUi } from '@bundles/fantastic_agent/web/chat-ui'
import { fantasticAgentPlugin } from '@bundles/fantastic_agent/plugin'

// ─── plugin registration ──────────────────────────────────────────

describe('fantasticAgentPlugin', () => {
  it('does not have injectCanvas (no canvas-level click handler)', () => {
    expect(fantasticAgentPlugin.injectCanvas).toBeUndefined()
  })

  it('matches agents with bundle fantastic_agent', () => {
    expect(fantasticAgentPlugin.matchAgent!({ bundle: 'fantastic_agent' } as any)).toBe(true)
    expect(fantasticAgentPlugin.matchAgent!({ bundle: 'terminal' } as any)).toBe(false)
  })
})

// ─── ai-connector ─────────────────────────────────────────────────

describe('createAiConnector', () => {
  let wsSend: ReturnType<typeof vi.fn>
  let events: {
    onResponseChunk: ReturnType<typeof vi.fn>
    onStateChange: ReturnType<typeof vi.fn>
    onError: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    wsSend = vi.fn()
    events = {
      onResponseChunk: vi.fn(),
      onStateChange: vi.fn(),
      onError: vi.fn(),
    }
  })

  it('sendTranscript sends voice_transcript with default mode', () => {
    const ai = createAiConnector('agent_1', wsSend, events)
    ai.sendTranscript('hello')

    expect(wsSend).toHaveBeenCalledWith({
      type: 'voice_transcript',
      agent_id: 'agent_1',
      text: 'hello',
      is_final: true,
      mode: 'voice',
    })
    expect(events.onStateChange).toHaveBeenCalledWith('thinking')
  })

  it('sendTranscript passes explicit mode', () => {
    const ai = createAiConnector('agent_1', wsSend, events)
    ai.sendTranscript('hi', 'chat')

    expect(wsSend).toHaveBeenCalledWith(
      expect.objectContaining({ mode: 'chat' })
    )
  })

  it('sendInterrupt clears buffer and resets state', () => {
    const ai = createAiConnector('agent_1', wsSend, events)
    ai.sendInterrupt()

    expect(wsSend).toHaveBeenCalledWith({
      type: 'voice_interrupt',
      agent_id: 'agent_1',
    })
    expect(events.onStateChange).toHaveBeenCalledWith('idle')
  })

  it('handleMessage ignores messages for other agents', () => {
    const ai = createAiConnector('agent_1', wsSend, events)
    ai.handleMessage({ type: 'voice_response', agent_id: 'agent_2', text: 'x', done: true })

    expect(events.onResponseChunk).not.toHaveBeenCalled()
  })

  it('handleMessage processes voice_response streaming', () => {
    const ai = createAiConnector('agent_1', wsSend, events)

    ai.handleMessage({ type: 'voice_response', agent_id: 'agent_1', text: 'chunk1', done: false })
    expect(events.onStateChange).toHaveBeenCalledWith('responding')
    expect(events.onResponseChunk).toHaveBeenCalledWith('chunk1', false)
  })

  it('handleMessage processes voice_response done', () => {
    const ai = createAiConnector('agent_1', wsSend, events)

    // First a streaming chunk
    ai.handleMessage({ type: 'voice_response', agent_id: 'agent_1', text: 'hello ', done: false })
    events.onResponseChunk.mockClear()

    // Then done
    ai.handleMessage({ type: 'voice_response', agent_id: 'agent_1', text: 'world', done: true })
    expect(events.onResponseChunk).toHaveBeenCalledWith('hello world', true)
  })

  it('handleMessage processes voice_state', () => {
    const ai = createAiConnector('agent_1', wsSend, events)
    ai.handleMessage({ type: 'voice_state', agent_id: 'agent_1', state: 'thinking' })

    expect(events.onStateChange).toHaveBeenCalledWith('thinking')
  })

  it('handleMessage processes voice_error', () => {
    const ai = createAiConnector('agent_1', wsSend, events)
    ai.handleMessage({ type: 'voice_error', agent_id: 'agent_1', error: 'fail' })

    expect(events.onError).toHaveBeenCalledWith('fail')
  })
})

// ─── chat-ui ──────────────────────────────────────────────────────

describe('createChatUi', () => {
  let wsSend: ReturnType<typeof vi.fn>
  let events: { onError: ReturnType<typeof vi.fn> }

  beforeEach(() => {
    wsSend = vi.fn()
    events = { onError: vi.fn() }
  })

  it('creates DOM with message list and input', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    const dom = chat.dom

    expect(dom.querySelector('.fa-chat-messages')).toBeTruthy()
    expect(dom.querySelector('.fa-chat-input')).toBeTruthy()
    expect(dom.querySelector('.fa-chat-send')).toBeTruthy()
    chat.destroy()
  })

  it('loadHistory renders messages', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    document.body.appendChild(chat.dom)

    chat.loadHistory([
      { role: 'user', text: 'hello', mode: 'voice' },
      { role: 'assistant', text: 'hi back', mode: 'voice' },
    ])

    const messages = chat.dom.querySelectorAll('.fa-chat-msg')
    expect(messages).toHaveLength(2)
    expect(messages[0].classList.contains('user')).toBe(true)
    expect(messages[0].textContent).toContain('hello')
    expect(messages[1].classList.contains('assistant')).toBe(true)

    chat.destroy()
  })

  it('loadHistory only runs once', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    document.body.appendChild(chat.dom)

    chat.loadHistory([{ role: 'user', text: 'first' }])
    chat.loadHistory([{ role: 'user', text: 'second' }])

    const messages = chat.dom.querySelectorAll('.fa-chat-msg')
    expect(messages).toHaveLength(1)
    expect(messages[0].textContent).toContain('first')

    chat.destroy()
  })

  it('appendMessage adds a message to the list', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    document.body.appendChild(chat.dom)

    chat.appendMessage('assistant', 'response text', 'chat')

    const messages = chat.dom.querySelectorAll('.fa-chat-msg')
    expect(messages).toHaveLength(1)
    expect(messages[0].textContent).toContain('response text')

    chat.destroy()
  })

  it('sends message on Enter key', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    document.body.appendChild(chat.dom)

    const input = chat.dom.querySelector('.fa-chat-input') as HTMLInputElement
    input.value = 'test message'
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))

    expect(wsSend).toHaveBeenCalledWith({
      type: 'voice_transcript',
      agent_id: 'agent_1',
      text: 'test message',
      is_final: true,
      mode: 'chat',
    })
    expect(input.value).toBe('')

    // User message rendered in list
    const messages = chat.dom.querySelectorAll('.fa-chat-msg.user')
    expect(messages).toHaveLength(1)

    chat.destroy()
  })

  it('sends message on send button click', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    document.body.appendChild(chat.dom)

    const input = chat.dom.querySelector('.fa-chat-input') as HTMLInputElement
    input.value = 'click message'

    const sendBtn = chat.dom.querySelector('.fa-chat-send') as HTMLButtonElement
    sendBtn.click()

    expect(wsSend).toHaveBeenCalledWith(
      expect.objectContaining({ text: 'click message', mode: 'chat' })
    )

    chat.destroy()
  })

  it('does not send empty messages', () => {
    const chat = createChatUi('agent_1', wsSend, events)
    document.body.appendChild(chat.dom)

    const input = chat.dom.querySelector('.fa-chat-input') as HTMLInputElement
    input.value = '   '
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))

    expect(wsSend).not.toHaveBeenCalled()

    chat.destroy()
  })
})
