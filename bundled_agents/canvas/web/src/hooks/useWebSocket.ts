import { useCallback, useEffect, useRef, useState } from 'react'
import type { WSMessage } from '../types'

interface PendingRequest {
  resolve: (data: unknown) => void
  reject: (err: Error) => void
  timeout: ReturnType<typeof setTimeout>
}

/** POST to /api/call — used as HTTP fallback when WS is unavailable. */
async function httpCall(tool: string, args: Record<string, unknown>): Promise<unknown> {
  const res = await fetch('/api/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool, args }),
  })
  const json = await res.json()
  if (json.error) throw new Error(json.error)
  return json.result
}

export function useWebSocket(url: string) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null)
  const listenersRef = useRef<Set<(msg: WSMessage) => void>>(new Set())
  const pendingRef = useRef<Map<string, PendingRequest>>(new Map())

  useEffect(() => {
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      // Request initial state
      ws.send(JSON.stringify({ type: 'get_state' }))
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data) as WSMessage

      // Resolve pending request if response carries a correlation ID
      const reqId = msg._req_id as string | undefined
      if (reqId) {
        const pending = pendingRef.current.get(reqId)
        if (pending) {
          clearTimeout(pending.timeout)
          pendingRef.current.delete(reqId)
          if (msg.type === 'error') {
            pending.reject(new Error(msg.message as string))
          } else {
            pending.resolve(msg.data)
          }
          return
        }
      }

      setLastMessage(msg)
      listenersRef.current.forEach((fn) => fn(msg))
    }

    ws.onclose = () => {
      setConnected(false)
    }

    ws.onerror = () => {
      setConnected(false)
    }

    return () => {
      ws.close()
      // Reject all pending requests on cleanup
      for (const [, p] of pendingRef.current) {
        clearTimeout(p.timeout)
        p.reject(new Error('WebSocket closed'))
      }
      pendingRef.current.clear()
    }
  }, [url])

  /** Fire-and-forget: WS if connected, else HTTP POST fallback. */
  const send = useCallback((msg: WSMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    } else {
      const { type, ...args } = msg
      httpCall(type, args).catch(() => {})
    }
  }, [])

  /** Promise-based request: WS with response correlation, HTTP fallback. */
  const request = useCallback((tool: string, args: Record<string, unknown> = {}): Promise<unknown> => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const reqId = crypto.randomUUID()
      return new Promise((resolve, reject) => {
        const timeout = setTimeout(() => {
          pendingRef.current.delete(reqId)
          httpCall(tool, args).then(resolve, reject)
        }, 5000)
        pendingRef.current.set(reqId, { resolve, reject, timeout })
        wsRef.current!.send(JSON.stringify({
          type: 'call', tool, args, _req_id: reqId,
        }))
      })
    }
    return httpCall(tool, args)
  }, [])

  const subscribe = useCallback((fn: (msg: WSMessage) => void) => {
    listenersRef.current.add(fn)
    return () => { listenersRef.current.delete(fn) }
  }, [])

  return { connected, lastMessage, send, subscribe, request }
}
