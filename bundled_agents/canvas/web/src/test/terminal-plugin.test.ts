/**
 * Tests for terminal plugin:
 *   - injectCanvas: dblclick creates terminal (no shiftKey guard)
 *   - injectHeader: autoscroll button + AI robot button
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { terminalPlugin } from '@bundles/terminal/plugin'
import type { CanvasAgent } from '../types'

function makeAgent(overrides: Partial<CanvasAgent> = {}): CanvasAgent {
  return {
    id: 'term_001',
    bundle: 'terminal',
    display_name: '',
    x: 100,
    y: 200,
    width: 800,
    height: 600,
    output_html: '',
    ...overrides,
  }
}

// ─── injectCanvas ────────────────────────────────────────────────

describe('terminal injectCanvas', () => {
  let dom: HTMLElement
  let send: ReturnType<typeof vi.fn>
  let cleanup: (() => void) | undefined

  beforeEach(() => {
    dom = document.createElement('div')
    send = vi.fn()
    cleanup = terminalPlugin.injectCanvas!(dom, {
      send,
      subscribe: vi.fn(() => () => {}),
      screenToCanvas: (e: MouseEvent) => ({ x: e.clientX, y: e.clientY }),
    })
  })

  afterEach(() => {
    cleanup?.()
  })

  it('dblclick on background creates terminal agent', () => {
    dom.dispatchEvent(new MouseEvent('dblclick', { clientX: 50, clientY: 60, bubbles: true }))
    expect(send).toHaveBeenCalledWith({
      type: 'create_agent',
      template: 'terminal',
      options: { x: 50, y: 60 },
    })
  })

  it('dblclick with shiftKey still creates terminal (no guard)', () => {
    dom.dispatchEvent(new MouseEvent('dblclick', { clientX: 10, clientY: 20, shiftKey: true, bubbles: true }))
    expect(send).toHaveBeenCalledWith({
      type: 'create_agent',
      template: 'terminal',
      options: { x: 10, y: 20 },
    })
  })

  it('dblclick on agent-wrapper does not create', () => {
    const wrapper = document.createElement('div')
    wrapper.className = 'agent-wrapper'
    dom.appendChild(wrapper)
    wrapper.dispatchEvent(new MouseEvent('dblclick', { clientX: 0, clientY: 0, bubbles: true }))
    expect(send).not.toHaveBeenCalled()
  })

  it('cleanup removes dblclick handler', () => {
    cleanup!()
    cleanup = undefined
    dom.dispatchEvent(new MouseEvent('dblclick', { clientX: 0, clientY: 0, bubbles: true }))
    expect(send).not.toHaveBeenCalled()
  })
})

// ─── injectHeader: AI robot button ──────────────────────────────

describe('terminal injectHeader AI button', () => {
  let dom: HTMLElement
  let send: ReturnType<typeof vi.fn>
  let cleanup: (() => void) | undefined

  beforeEach(() => {
    dom = document.createElement('div')
    // Wrap in .agent-shape for getIframe() traversal
    const shape = document.createElement('div')
    shape.className = 'agent-shape'
    shape.appendChild(dom)
    document.body.appendChild(shape)

    send = vi.fn()
    cleanup = terminalPlugin.injectHeader!(dom, {
      agent: makeAgent(),
      send,
      subscribe: vi.fn(() => () => {}),
    })
  })

  afterEach(() => {
    cleanup?.()
    document.body.innerHTML = ''
  })

  it('injects two buttons (autoscroll + AI)', () => {
    const buttons = dom.querySelectorAll('button.agent-header-btn')
    expect(buttons.length).toBe(2)
  })

  it('AI button has robot icon image', () => {
    const buttons = dom.querySelectorAll('button.agent-header-btn')
    const aiBtn = buttons[1]
    expect(aiBtn.title).toBe('Open AI agent')
    const img = aiBtn.querySelector('img')
    expect(img).toBeTruthy()
    expect(img!.src).toContain('favicon.png')
  })

  it('clicking AI button sends create_agent for fantastic_agent', () => {
    const buttons = dom.querySelectorAll('button.agent-header-btn')
    const aiBtn = buttons[1] as HTMLButtonElement
    aiBtn.click()
    expect(send).toHaveBeenCalledWith({
      type: 'create_agent',
      template: 'ollama',
      options: { x: 100 + 800 + 20, y: 200 },
    })
  })

  it('AI button positions agent to the right of terminal', () => {
    // Agent at x=100, width=800 → new agent at x=920
    const agent = makeAgent({ x: 50, width: 400 })
    dom.innerHTML = ''
    cleanup?.()
    cleanup = terminalPlugin.injectHeader!(dom, {
      agent,
      send,
      subscribe: vi.fn(() => () => {}),
    })

    const buttons = dom.querySelectorAll('button.agent-header-btn')
    const aiBtn = buttons[1] as HTMLButtonElement
    aiBtn.click()
    expect(send).toHaveBeenCalledWith({
      type: 'create_agent',
      template: 'ollama',
      options: { x: 50 + 400 + 20, y: agent.y },
    })
  })

  it('cleanup removes both buttons', () => {
    cleanup!()
    cleanup = undefined
    expect(dom.querySelectorAll('button.agent-header-btn').length).toBe(0)
  })
})
