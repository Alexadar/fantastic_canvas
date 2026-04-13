/**
 * Thin shim over window.fantastic_transport(). Preserves the {send, subscribe, request}
 * interface canvas components already use, but routes through the injected transport.
 *
 * - send({type, ...args})   → transport.dispatch(type, args) (fire-and-forget)
 * - request(tool, args)     → transport.dispatch(tool, args) (awaits reply)
 * - subscribe(fn)           → transport.onAny — fn receives WS-like {type, ...data}
 *
 * No REST fallback. No manual WebSocket construction. Transport hides everything.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { TransportMessage } from '../types'

// Loose types; transport is injected at runtime by web bundle.
type Transport = {
  agentId: string
  dispatch(tool: string, args?: Record<string, unknown>): Promise<unknown>
  dispatcher: Record<string, (args?: Record<string, unknown>) => Promise<unknown>>
  emit(event: string, data?: Record<string, unknown>): void
  on(event: string, handler: (data: any) => void): () => void
  onAny(handler: (event: string, data: any) => void): () => void
  watch(agentId: string): Promise<void>
  unwatch(agentId: string): Promise<void>
}

declare global {
  interface Window {
    fantastic_transport(): Transport
  }
}

export function useTransport(_url?: string) {
  const tRef = useRef<Transport | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<TransportMessage | null>(null)
  const listenersRef = useRef<Set<(msg: TransportMessage) => void>>(new Set())

  useEffect(() => {
    // The transport is injected by the web bundle as a global.
    const t = window.fantastic_transport()
    tRef.current = t
    setConnected(true)

    const off = t.onAny((event, data) => {
      const msg = { type: event, ...(data || {}) } as TransportMessage
      setLastMessage(msg)
      listenersRef.current.forEach((fn) => fn(msg))
    })

    // Kick off initial state fetch — backend returns ToolResult.data
    t.dispatch('get_state').then((data) => {
      const msg = { type: 'state', state: data } as TransportMessage
      setLastMessage(msg)
      listenersRef.current.forEach((fn) => fn(msg))
    }).catch(() => {})

    return () => { off() }
  }, [])

  const send = useCallback((msg: TransportMessage) => {
    const t = tRef.current
    if (!t) return
    const { type, ...args } = msg as any
    t.dispatch(type as string, args).catch(() => {})
  }, [])

  const request = useCallback((tool: string, args: Record<string, unknown> = {}): Promise<unknown> => {
    const t = tRef.current
    if (!t) return Promise.reject(new Error('transport not ready'))
    return t.dispatch(tool, args)
  }, [])

  const subscribe = useCallback((fn: (msg: TransportMessage) => void) => {
    listenersRef.current.add(fn)
    return () => { listenersRef.current.delete(fn) }
  }, [])

  return { connected, lastMessage, send, subscribe, request }
}
