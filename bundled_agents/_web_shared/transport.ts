/**
 * fantastic_transport — injected global for every agent HTML page.
 *
 * UI code calls `fantastic_transport()` to get an opaque transport object.
 * It hides WebSocket entirely. Call / emit / on / watch. That's it.
 *
 * Build: esbuild transport.ts --bundle --format=iife --outfile=transport.js
 * (or hand-transcribed; see transport.js for the current distributed artifact)
 *
 * Served by web bundle at {base}/_fantastic/transport.js and injected as the
 * first <script> in every agent HTML. Zero imports needed in agent pages.
 */

export interface Transport {
  readonly agentId: string
  // Symmetric with backend _DISPATCH: same tool name, same args
  dispatch(tool: string, args?: Record<string, any>): Promise<any>
  // Proxy sugar — `transport.dispatcher.list_agents({parent: "..."})` === dispatch("list_agents", {parent: "..."})
  readonly dispatcher: Record<string, (args?: Record<string, any>) => Promise<any>>
  // Events (pub/sub; separate from dispatch)
  emit(event: string, data?: Record<string, any>): void
  on(event: string, handler: (data: any) => void): () => void
  // Wildcard listener (useful for canvas/dashboard that watch many event types)
  onAny(handler: (event: string, data: any) => void): () => void
  // Mirror another agent's inbox into mine
  watch(agentId: string): Promise<void>
  unwatch(agentId: string): Promise<void>
  // Self-description for LLM introspection
  description(): TransportDescription
}

export interface TransportDescription {
  version: string
  agentId: string
  baseUrl: string
  messageShapes: Record<string, any>
  capabilities: string[]
  example: { ts: string; js: string }
  howToUse: string
}

const PROTOCOL_VERSION = '1.0'

const HOW_TO_USE = `
# fantastic_transport

A page-scoped bridge to the Fantastic Canvas orchestrator.
Dispatch names MIRROR the backend _DISPATCH registry 1:1.

## Basic usage

\`\`\`ts
const t = fantastic_transport()

// Dispatch: symmetric with backend. Same names, same args.
const state = await t.dispatch('get_state')
await t.dispatch('create_agent', {template: 'terminal'})

// Sugar via Proxy — cleaner call sites
const d = t.dispatcher
await d.list_agents({parent: 'canvas_main'})
await d.process_restart({agent_id: 'terminal_xyz'})

// Events (separate from dispatch — async push)
t.on('agent_moved', m => console.log(m.agent_id))
t.emit('my_custom_event', {foo: 'bar'})

// Watch another agent (mirror their events into your inbox)
await t.watch('ollama_abc123')
t.on('ollama_response', chunk => console.log(chunk.text))
\`\`\`

## Rule

Every \`t.dispatch(name, args)\` on the frontend maps to backend
\`_DISPATCH[name](**args)\`. No aliasing, no translation.
Discover names via \`await t.dispatch('get_handbook')\`.

## Events

Backend emits events into your inbox (e.g. \`agent_created\`,
\`process_output\`, \`{bundle}_response\`, \`context_usage\`). Subscribe
with \`t.on(name, handler)\`. Use \`t.watch(other_id)\` to ALSO receive
events destined for another agent.
`.trim()

const EXAMPLE_TS = `
const t = fantastic_transport()
const d = t.dispatcher  // Proxy sugar

await d.create_agent({template: 'terminal'})
const agents = await d.list_agents()
t.on('process_output', e => console.log(e.data))
`.trim()

const EXAMPLE_JS = EXAMPLE_TS

function parseAgentIdFromUrl(): string {
  // URL shape: /{base?}/{agent_id}/...
  // We assume the LAST non-empty path segment before trailing slash or file
  // is the agent id — or the first segment after a recognized base route.
  // Simplest heuristic: take first non-empty path segment.
  const parts = window.location.pathname.split('/').filter(Boolean)
  if (parts.length === 0) return ''
  // Skip leading "_fantastic" or empty base
  return parts[0]
}

function connect(agentId: string): Transport {
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${wsProto}//${window.location.host}/${agentId}/ws`

  let ws: WebSocket | null = null
  const pending = new Map<string, { resolve: (v: any) => void; reject: (e: any) => void }>()
  const listeners = new Map<string, Set<(data: any) => void>>()
  const anyListeners = new Set<(event: string, data: any) => void>()
  const outbox: string[] = []
  let connected = false

  const open = () => {
    ws = new WebSocket(wsUrl)
    ws.onopen = () => {
      connected = true
      while (outbox.length > 0) {
        ws!.send(outbox.shift()!)
      }
    }
    ws.onmessage = (ev) => {
      let msg: any
      try { msg = JSON.parse(ev.data) } catch { return }
      if (msg.type === 'reply') {
        const p = pending.get(msg.id)
        if (p) { pending.delete(msg.id); p.resolve(msg.data) }
      } else if (msg.type === 'error') {
        const p = pending.get(msg.id)
        if (p) { pending.delete(msg.id); p.reject(new Error(msg.error || 'unknown error')) }
      } else if (msg.type === 'event') {
        const handlers = listeners.get(msg.event)
        if (handlers) {
          for (const h of handlers) { try { h(msg.data) } catch (e) { console.error(e) } }
        }
        for (const h of anyListeners) { try { h(msg.event, msg.data) } catch (e) { console.error(e) } }
      }
    }
    ws.onclose = () => {
      connected = false
      ws = null
      // Exponential reconnect
      setTimeout(open, 1000)
    }
    ws.onerror = () => {
      // onclose fires next
    }
  }
  open()

  const send = (obj: any) => {
    const payload = JSON.stringify(obj)
    if (connected && ws && ws.readyState === WebSocket.OPEN) {
      ws.send(payload)
    } else {
      outbox.push(payload)
    }
  }

  const genId = () => Math.random().toString(36).slice(2) + Date.now().toString(36)

  const dispatch = (tool: string, args?: Record<string, any>): Promise<any> => {
    const id = genId()
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject })
      send({ type: 'call', tool, args: args || {}, id })
    })
  }

  const dispatcher = new Proxy({} as any, {
    get(_target, name: string) {
      return (args?: Record<string, any>) => dispatch(name, args)
    },
  })

  const transport: Transport = {
    agentId,
    dispatch,
    dispatcher,

    emit(event: string, data?: Record<string, any>) {
      send({ type: 'emit', event, data: data || {} })
    },

    on(event: string, handler: (data: any) => void) {
      let set = listeners.get(event)
      if (!set) { set = new Set(); listeners.set(event, set) }
      set.add(handler)
      return () => { set!.delete(handler) }
    },

    onAny(handler: (event: string, data: any) => void) {
      anyListeners.add(handler)
      return () => { anyListeners.delete(handler) }
    },

    async watch(otherId: string) {
      await dispatch('_bus_watch', { source: otherId })
    },

    async unwatch(otherId: string) {
      await dispatch('_bus_unwatch', { source: otherId })
    },

    description(): TransportDescription {
      return {
        version: PROTOCOL_VERSION,
        agentId,
        baseUrl: window.location.origin,
        capabilities: ['dispatch', 'events', 'bidirectional', 'watch'],
        messageShapes: {
          call: { type: 'call', tool: 'string', args: 'object', id: 'uuid' },
          emit: { type: 'emit', event: 'string', data: 'object' },
          reply: { type: 'reply', id: 'uuid', data: 'object' },
          error: { type: 'error', id: 'uuid', error: 'string' },
          event: { type: 'event', event: 'string', data: 'object' },
        },
        example: { ts: EXAMPLE_TS, js: EXAMPLE_JS },
        howToUse: HOW_TO_USE,
      }
    },
  }

  return transport
}

// Install global
;(window as any).fantastic_transport = function fantastic_transport(): Transport {
  const agentId = parseAgentIdFromUrl()
  if (!agentId) {
    throw new Error('fantastic_transport: could not parse agent_id from URL')
  }
  return connect(agentId)
}
