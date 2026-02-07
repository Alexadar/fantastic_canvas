import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from '../hooks/useWebSocket'

// Mock WebSocket
class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []

  url: string
  readyState = MockWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sentMessages: string[] = []

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
    // Don't auto-fire onopen — tests trigger it manually via act()
  }

  send(data: string) {
    this.sentMessages.push(data)
  }

  close() {
    this.readyState = 3 // CLOSED
    this.onclose?.()
  }

  // Test helper: simulate receiving a message
  simulateMessage(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) })
  }
}

// Mock fetch for HTTP fallback tests
function mockFetch(response: unknown = { result: 'ok' }) {
  return vi.fn(() =>
    Promise.resolve({
      json: () => Promise.resolve(response),
    } as Response),
  )
}

describe('useWebSocket', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    vi.stubGlobal('fetch', mockFetch())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates WebSocket with given URL', () => {
    renderHook(() => useWebSocket('ws://localhost:8888/ws'))
    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0].url).toBe('ws://localhost:8888/ws')
  })

  it('sets connected to true after open', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    // Initially not connected
    expect(result.current.connected).toBe(false)

    // Simulate open
    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    expect(result.current.connected).toBe(true)
  })

  it('sends get_state on connection', async () => {
    renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    const sent = MockWebSocket.instances[0].sentMessages
    expect(sent).toHaveLength(1)
    expect(JSON.parse(sent[0])).toEqual({ type: 'get_state' })
  })

  it('sets connected to false on close', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })
    expect(result.current.connected).toBe(true)

    await act(async () => {
      MockWebSocket.instances[0].onclose?.()
    })
    expect(result.current.connected).toBe(false)
  })

  it('sets connected to false on error', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    await act(async () => {
      MockWebSocket.instances[0].onerror?.()
    })
    expect(result.current.connected).toBe(false)
  })

  it('send() sends JSON message when connected', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    act(() => {
      result.current.send({ type: 'create_agent', x: 10, y: 20 })
    })

    const sent = MockWebSocket.instances[0].sentMessages
    // First message is get_state, second is our message
    expect(sent).toHaveLength(2)
    expect(JSON.parse(sent[1])).toEqual({ type: 'create_agent', x: 10, y: 20 })
  })

  it('send() falls back to HTTP when not connected', async () => {
    const fetchMock = mockFetch()
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    // Change readyState to not OPEN
    MockWebSocket.instances[0].readyState = 3

    await act(async () => {
      result.current.send({ type: 'create_agent', x: 10, y: 20 })
    })

    // No WS messages sent
    expect(MockWebSocket.instances[0].sentMessages).toHaveLength(0)

    // HTTP fallback called
    expect(fetchMock).toHaveBeenCalledWith('/api/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: 'create_agent', args: { x: 10, y: 20 } }),
    })
  })

  it('updates lastMessage on incoming message', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].simulateMessage({
        type: 'agent_created',
        agent: { id: 'abc' },
      })
    })

    expect(result.current.lastMessage).toEqual({
      type: 'agent_created',
      agent: { id: 'abc' },
    })
  })

  it('subscribe receives messages', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))
    const listener = vi.fn()

    act(() => {
      result.current.subscribe(listener)
    })

    await act(async () => {
      MockWebSocket.instances[0].simulateMessage({ type: 'state', state: {} })
    })

    expect(listener).toHaveBeenCalledWith({ type: 'state', state: {} })
  })

  it('unsubscribe stops receiving messages', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))
    const listener = vi.fn()
    let unsub: () => void

    act(() => {
      unsub = result.current.subscribe(listener)
    })

    await act(async () => {
      MockWebSocket.instances[0].simulateMessage({ type: 'msg1' })
    })
    expect(listener).toHaveBeenCalledTimes(1)

    // Unsubscribe
    act(() => {
      unsub()
    })

    await act(async () => {
      MockWebSocket.instances[0].simulateMessage({ type: 'msg2' })
    })
    // Should not receive msg2
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('multiple subscribers all receive messages', async () => {
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))
    const listener1 = vi.fn()
    const listener2 = vi.fn()

    act(() => {
      result.current.subscribe(listener1)
      result.current.subscribe(listener2)
    })

    await act(async () => {
      MockWebSocket.instances[0].simulateMessage({ type: 'test' })
    })

    expect(listener1).toHaveBeenCalledTimes(1)
    expect(listener2).toHaveBeenCalledTimes(1)
  })

  it('closes WebSocket on unmount', () => {
    const { unmount } = renderHook(() => useWebSocket('ws://test/ws'))
    const ws = MockWebSocket.instances[0]
    unmount()
    expect(ws.readyState).toBe(3) // CLOSED
  })

  // ─── request() tests ──────────────────────────────────────────────

  it('request() sends call via WS and resolves on call_result', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'test-uuid-123' })
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    let resolved: unknown
    await act(async () => {
      const promise = result.current.request('list_files', { path: '/' })

      // Verify WS message sent with call wrapper
      const sent = MockWebSocket.instances[0].sentMessages
      const lastMsg = JSON.parse(sent[sent.length - 1])
      expect(lastMsg).toEqual({
        type: 'call',
        tool: 'list_files',
        args: { path: '/' },
        _req_id: 'test-uuid-123',
      })

      // Simulate server response with matching _req_id
      MockWebSocket.instances[0].simulateMessage({
        type: 'call_result',
        tool: 'list_files',
        data: { files: ['a.py'] },
        _req_id: 'test-uuid-123',
      })

      resolved = await promise
    })

    expect(resolved).toEqual({ files: ['a.py'] })
  })

  it('request() falls back to HTTP when WS is closed', async () => {
    const fetchMock = mockFetch({ result: { files: ['b.py'] } })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useWebSocket('ws://test/ws'))
    MockWebSocket.instances[0].readyState = 3

    let resolved: unknown
    await act(async () => {
      resolved = await result.current.request('list_files', { path: '/' })
    })

    expect(fetchMock).toHaveBeenCalledWith('/api/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool: 'list_files', args: { path: '/' } }),
    })
    expect(resolved).toEqual({ files: ['b.py'] })
  })

  it('request() rejects on WS error response with _req_id', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'err-uuid' })
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    await act(async () => {
      const promise = result.current.request('bad_tool')

      // Simulate error response
      MockWebSocket.instances[0].simulateMessage({
        type: 'error',
        message: 'Unknown tool',
        _req_id: 'err-uuid',
      })

      await expect(promise).rejects.toThrow('Unknown tool')
    })
  })

  it('correlated call_result does not broadcast to subscribers', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'corr-uuid' })
    const { result } = renderHook(() => useWebSocket('ws://test/ws'))
    const listener = vi.fn()

    await act(async () => {
      MockWebSocket.instances[0].onopen?.()
    })

    act(() => {
      result.current.subscribe(listener)
    })

    await act(async () => {
      const promise = result.current.request('some_tool')

      MockWebSocket.instances[0].simulateMessage({
        type: 'call_result',
        data: 'done',
        _req_id: 'corr-uuid',
      })

      await promise
    })

    // Listener should NOT have been called for the correlated response
    expect(listener).not.toHaveBeenCalled()
  })
})
