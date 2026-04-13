import { useCallback, useEffect, useRef, useState } from 'react'
import type { CanvasAgent, TransportMessage } from '../types'
import { useTransport } from '../hooks/useTransport'
import { AgentShape } from './AgentShape'
import { registry } from '../plugins/registry'
import { WebGLLayer } from './WebGLLayer'
import type { ViewState, WorldClick } from './WebGLLayer'
import { domToWorld } from './coordBridge'

// No WS here — all transport is hidden inside fantastic_transport() (see useTransport).
// Broadcast viewer mode becomes a separate readonly web agent in the new model (# later).
const isViewer = false

const INITIAL_ZOOM = 1
const DEFAULT_ANCHOR: [number, number, number] = [0, 0, 0]

interface DragState {
  id: string
  mouseX: number
  mouseY: number
  agentX: number
  agentY: number
  currentX: number
  currentY: number
}

type ResizeDirection = 'top' | 'right' | 'bottom' | 'left' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'

interface ResizeState {
  id: string
  direction: ResizeDirection
  mouseX: number
  mouseY: number
  agentX: number
  agentY: number
  agentWidth: number
  agentHeight: number
  currentX: number
  currentY: number
  currentWidth: number
  currentHeight: number
}

interface CanvasProps {
  canvasName?: string
}

export function Canvas({ canvasName }: CanvasProps = {}) {
  const { send, subscribe } = useTransport()
  const [agents, setAgents] = useState<Map<string, CanvasAgent>>(new Map())
  const [view, setView] = useState<ViewState>({ offsetX: 0, offsetY: 0, zoom: 1, anchor: DEFAULT_ANCHOR, domVisible: true })
  const [activeAgentId, setActiveAgentId] = useState<string | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const isPanning = useRef(false)
  const lastMouse = useRef({ x: 0, y: 0 })
  const dragging = useRef<DragState | null>(null)
  const resizing = useRef<ResizeState | null>(null)
  const viewRef = useRef(view)
  viewRef.current = view
  const agentsRef = useRef(agents)
  agentsRef.current = agents
  // Expose agents to VFX background (runs in sandboxed Function, can't access React state)
  ;(window as any).__canvasState = { agents: Array.from(agents.values()) }
  const initialLoadDone = useRef(false)
  const panStartMouse = useRef<{ x: number; y: number } | null>(null)

  // VFX state (rendered by WebGL layer)
  const [sceneVfxJs, setSceneVfxJs] = useState<string | null>(null)
  const [worldClick, setWorldClick] = useState<WorldClick | null>(null)

  // ─── Plugin injection into canvas ─────────────────────
  useEffect(() => {
    if (!canvasRef.current) return
    return registry.injectAll(canvasRef.current, {
      send,
      subscribe,
      screenToCanvas: (e: MouseEvent) => {
        const rect = canvasRef.current!.getBoundingClientRect()
        const v = viewRef.current
        return {
          x: Math.round((e.clientX - rect.left - v.offsetX) / v.zoom),
          y: Math.round((e.clientY - rect.top - v.offsetY) / v.zoom),
        }
      },
    })
  }, [send, subscribe])


  // Clear worldClick after one frame so it's a one-shot event
  useEffect(() => {
    if (!worldClick) return
    const id = requestAnimationFrame(() => setWorldClick(null))
    return () => cancelAnimationFrame(id)
  }, [worldClick])

  // ─── Subscribe to WS messages ───────────────────────
  useEffect(() => {
    return subscribe((msg: TransportMessage) => {
      switch (msg.type) {
        case 'state': {
          const state = msg.state as { agents: CanvasAgent[]; scene_vfx_js?: string; bg_vfx_js?: string }
          const map = new Map<string, CanvasAgent>()
          for (const agent of state?.agents || []) {
            map.set(agent.id, agent)
          }
          setAgents(map)
          if (state?.scene_vfx_js || state?.bg_vfx_js) {
            setSceneVfxJs(state.scene_vfx_js || state.bg_vfx_js || null)
          }
          // On initial load, center viewport on first agent or (0,0)
          if (!initialLoadDone.current) {
            initialLoadDone.current = true
            const vw = window.innerWidth
            const vh = window.innerHeight
            setView(v => ({
              ...v,
              offsetX: Math.round(vw / 2),
              offsetY: Math.round(vh / 2),
            }))
          }
          break
        }
        case 'scene_vfx_updated':
        case 'vfx_bg_updated': {
          setSceneVfxJs(msg.js as string)
          break
        }
        case 'scene_vfx_data':
        case 'vfx_data': {
          ;(window as any).__vfxData = msg.data
          break
        }
        case 'agent_created': {
          const agent = msg.agent as CanvasAgent
          // If agent was created off-screen (e.g. by REST API), reposition to viewport center
          const v = viewRef.current
          const vw = window.innerWidth
          const vh = window.innerHeight
          const visLeft = -v.offsetX / v.zoom
          const visTop = -v.offsetY / v.zoom
          const visRight = visLeft + vw / v.zoom
          const visBottom = visTop + vh / v.zoom
          const onScreen = agent.x < visRight && agent.x + agent.width > visLeft &&
                           agent.y < visBottom && agent.y + agent.height > visTop
          if (!onScreen) {
            agent.x = Math.round(visLeft + (vw / v.zoom - agent.width) / 2)
            agent.y = Math.round(visTop + (vh / v.zoom - agent.height) / 2)
            send({ type: 'move_agent', agent_id: agent.id, x: agent.x, y: agent.y })
          }
          setAgents((prev) => new Map(prev).set(agent.id, agent))
          setActiveAgentId(agent.id)
          break
        }
        case 'agent_moved': {
          const id = msg.agent_id as string
          setAgents((prev) => {
            const next = new Map(prev)
            const existing = next.get(id)
            if (existing) {
              next.set(id, { ...existing, x: msg.x as number, y: msg.y as number })
            }
            return next
          })
          break
        }
        case 'agent_resized': {
          const id = msg.agent_id as string
          setAgents((prev) => {
            const next = new Map(prev)
            const existing = next.get(id)
            if (existing) {
              const updates: Partial<CanvasAgent> = {}
              if (msg.width != null) updates.width = msg.width as number
              if (msg.height != null) updates.height = msg.height as number
              next.set(id, { ...existing, ...updates })
            }
            return next
          })
          break
        }
        case 'agent_updated': {
          const id = msg.agent_id as string
          setAgents((prev) => {
            const next = new Map(prev)
            const existing = next.get(id)
            if (existing) {
              const { type: _, agent_id: __, ...updates } = msg
              next.set(id, { ...existing, ...updates } as CanvasAgent)
            }
            return next
          })
          break
        }
        case 'agent_deleted': {
          const id = msg.agent_id as string
          setAgents((prev) => {
            const next = new Map(prev)
            next.delete(id)
            return next
          })
          break
        }
        case 'agent_output': {
          const id = msg.agent_id as string
          if (msg.output_html) {
            setAgents((prev) => {
              const next = new Map(prev)
              const existing = next.get(id)
              if (existing) {
                const updates: Partial<CanvasAgent> = { output_html: msg.output_html as string }
                // For iframe agents, also update html_content so the iframe re-renders
                if (existing.has_iframe) {
                  updates.html_content = msg.output_html as string
                }
                next.set(id, { ...existing, ...updates })
              }
              return next
            })
          }
          break
        }
        case 'agent_refresh': {
          const id = msg.agent_id as string
          // Force iframe reload by toggling a refresh counter
          setAgents((prev) => {
            const next = new Map(prev)
            const existing = next.get(id)
            if (existing) {
              next.set(id, { ...existing, _refreshKey: (existing._refreshKey || 0) + 1 })
            }
            return next
          })
          break
        }
        case 'reload': {
          window.location.reload()
          break
        }
        case 'process_started':
        case 'process_closed':
        case 'instances_changed':
        case 'files_changed':
          break  // acknowledged, no UI action needed
      }
    })
  }, [subscribe, send])

  // ─── Window-level mouse tracking for drag/resize/pan
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (dragging.current) {
        const d = dragging.current
        const zoom = viewRef.current.zoom
        d.currentX = Math.round(d.agentX + (e.clientX - d.mouseX) / zoom)
        d.currentY = Math.round(d.agentY + (e.clientY - d.mouseY) / zoom)
        setAgents((prev) => {
          const next = new Map(prev)
          const agent = next.get(d.id)
          if (agent) {
            next.set(d.id, { ...agent, x: d.currentX, y: d.currentY })
          }
          return next
        })
      } else if (resizing.current) {
        const r = resizing.current
        const zoom = viewRef.current.zoom
        const dx = (e.clientX - r.mouseX) / zoom
        const dy = (e.clientY - r.mouseY) / zoom
        const dir = r.direction
        const growsRight = dir === 'right' || dir === 'top-right' || dir === 'bottom-right'
        const growsLeft = dir === 'left' || dir === 'top-left' || dir === 'bottom-left'
        const growsDown = dir === 'bottom' || dir === 'bottom-left' || dir === 'bottom-right'
        const growsUp = dir === 'top' || dir === 'top-left' || dir === 'top-right'
        if (growsRight) {
          r.currentWidth = Math.max(250, Math.round(r.agentWidth + dx))
        }
        if (growsLeft) {
          const newW = Math.max(250, Math.round(r.agentWidth - dx))
          r.currentX = Math.round(r.agentX + r.agentWidth - newW)
          r.currentWidth = newW
        }
        if (growsDown) {
          r.currentHeight = Math.max(100, Math.round(r.agentHeight + dy))
        }
        if (growsUp) {
          const newH = Math.max(100, Math.round(r.agentHeight - dy))
          r.currentY = Math.round(r.agentY + r.agentHeight - newH)
          r.currentHeight = newH
        }
        setAgents((prev) => {
          const next = new Map(prev)
          const agent = next.get(r.id)
          if (agent) {
            next.set(r.id, { ...agent, x: r.currentX, y: r.currentY, width: r.currentWidth, height: r.currentHeight })
          }
          return next
        })
      } else if (isPanning.current) {
        const dx = e.clientX - lastMouse.current.x
        const dy = e.clientY - lastMouse.current.y
        lastMouse.current = { x: e.clientX, y: e.clientY }
        setView(v => ({ ...v, offsetX: v.offsetX + dx, offsetY: v.offsetY + dy }))
      }
    }

    const onUp = () => {
      if (dragging.current) {
        const d = dragging.current
        send({ type: 'move_agent', agent_id: d.id, x: d.currentX, y: d.currentY })
        dragging.current = null
        document.body.style.cursor = ''
        canvasRef.current?.classList.remove('canvas-dragging')
      }
      if (resizing.current) {
        const r = resizing.current
        let { currentWidth, currentHeight, currentX, currentY } = r
        const dir = r.direction
        const growsLeft = dir === 'left' || dir === 'top-left' || dir === 'bottom-left'
        const growsUp = dir === 'top' || dir === 'top-left' || dir === 'top-right'
        // Apply size + position locally
        setAgents((prev) => {
          const next = new Map(prev)
          const agent = next.get(r.id)
          if (agent) next.set(r.id, { ...agent, x: currentX, y: currentY, width: currentWidth, height: currentHeight })
          return next
        })
        if (currentX !== r.agentX || currentY !== r.agentY) {
          send({ type: 'move_agent', agent_id: r.id, x: currentX, y: currentY })
        }
        send({ type: 'resize_agent', agent_id: r.id, width: currentWidth, height: currentHeight })
        resizing.current = null
        document.body.style.cursor = ''
        canvasRef.current?.classList.remove('canvas-dragging')
      }
      isPanning.current = false
    }

    // Ctrl+mousedown anywhere (including over agents) starts a pan
    const onDown = (e: MouseEvent) => {
      if (e.button === 0 && e.ctrlKey && !dragging.current && !resizing.current) {
        isPanning.current = true
        lastMouse.current = { x: e.clientX, y: e.clientY }
        canvasRef.current?.classList.add('canvas-dragging')
        document.body.style.cursor = 'grabbing'
        e.preventDefault()
      }
    }

    const onUpPan = () => {
      if (isPanning.current) {
        canvasRef.current?.classList.remove('canvas-dragging')
        document.body.style.cursor = ''
      }
    }

    window.addEventListener('mousedown', onDown, true)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    window.addEventListener('mouseup', onUpPan)
    return () => {
      window.removeEventListener('mousedown', onDown, true)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      window.removeEventListener('mouseup', onUpPan)
    }
  }, [send])

  const handleDragStart = useCallback((agentId: string, agentX: number, agentY: number, e: React.MouseEvent) => {
    if (isViewer) return
    dragging.current = { id: agentId, mouseX: e.clientX, mouseY: e.clientY, agentX, agentY, currentX: agentX, currentY: agentY }
    setActiveAgentId(agentId)
    document.body.style.cursor = 'grabbing'
    canvasRef.current?.classList.add('canvas-dragging')
    e.preventDefault()
    e.stopPropagation()
  }, [])

  const handleResizeStart = useCallback((agentId: string, direction: ResizeDirection, e: React.MouseEvent) => {
    if (isViewer) return
    const agent = agents.get(agentId)
    if (!agent) return
    setActiveAgentId(agentId)
    resizing.current = {
      id: agentId,
      direction,
      mouseX: e.clientX,
      mouseY: e.clientY,
      agentX: agent.x,
      agentY: agent.y,
      agentWidth: agent.width,
      agentHeight: agent.height,
      currentX: agent.x,
      currentY: agent.y,
      currentWidth: agent.width,
      currentHeight: agent.height,
    }
    const cursorMap: Record<ResizeDirection, string> = {
      'top': 'ns-resize', 'bottom': 'ns-resize',
      'left': 'ew-resize', 'right': 'ew-resize',
      'top-left': 'nwse-resize', 'bottom-right': 'nwse-resize',
      'top-right': 'nesw-resize', 'bottom-left': 'nesw-resize',
    }
    document.body.style.cursor = cursorMap[direction]
    canvasRef.current?.classList.add('canvas-dragging')
  }, [agents])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Pan on: middle-click, Alt+click, or left-click on canvas background
    // (Ctrl+click pan is handled at window level to work over agents too)
    const isExplicitPan = e.button === 1 || (e.button === 0 && e.altKey)
    const onBackground = !(e.target as HTMLElement).closest('.agent-wrapper')
    if (isExplicitPan || (e.button === 0 && onBackground)) {
      isPanning.current = true
      lastMouse.current = { x: e.clientX, y: e.clientY }
      panStartMouse.current = { x: e.clientX, y: e.clientY }
      e.preventDefault()
    }
  }, [])

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    // Fire worldClick only if background click didn't drag (< 5px movement)
    if (panStartMouse.current && e.button === 0 && canvasRef.current) {
      const dx = e.clientX - panStartMouse.current.x
      const dy = e.clientY - panStartMouse.current.y
      if (dx * dx + dy * dy < 25) {
        const rect = canvasRef.current.getBoundingClientRect()
        const v = viewRef.current
        const canvasX = Math.round((e.clientX - rect.left - v.offsetX) / v.zoom)
        const canvasY = Math.round((e.clientY - rect.top - v.offsetY) / v.zoom)
        const [wx, wy, wz] = domToWorld(canvasX, canvasY, v.anchor)
        setWorldClick({ x: wx, y: wy, z: wz })
      }
    }
    panStartMouse.current = null
  }, [])

  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (!e.metaKey && (e.target as HTMLElement).closest('.agent-shape')) return
    e.preventDefault()
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    setView(v => {
      const newZoom = Math.max(0.1, Math.min(5, v.zoom * (e.deltaY > 0 ? 0.95 : 1.05)))
      const scale = newZoom / v.zoom
      return { ...v, zoom: newZoom, offsetX: mx - (mx - v.offsetX) * scale, offsetY: my - (my - v.offsetY) * scale }
    })
  }, [])

  return (
    <div
      ref={canvasRef}
      className="canvas-surface"
      onMouseDown={handleMouseDown}
      onMouseUp={handleMouseUp}
      onWheel={handleWheel}
    >
      {/* SVG filter definition for liquid glass distortion (shared by all agents) */}
      <svg style={{ position: 'absolute', width: 0, height: 0 }} aria-hidden="true">
        <defs>
          <filter id="glass-distortion" x="0%" y="0%" width="100%" height="100%">
            <feTurbulence type="fractalNoise" baseFrequency="0.015 0.015"
              numOctaves={1} seed={5} result="turbulence" />
            <feGaussianBlur in="turbulence" stdDeviation={3} result="softMap" />
            <feSpecularLighting in="softMap" surfaceScale={3} specularConstant={0.6}
              specularExponent={80} lightingColor="white" result="specLight">
              <fePointLight x={-200} y={-200} z={300} />
            </feSpecularLighting>
            <feComposite in="specLight" operator="arithmetic"
              k1={0} k2={1} k3={1} k4={0} result="litImage" />
            <feDisplacementMap in="SourceGraphic" in2="softMap"
              scale={60} xChannelSelector="R" yChannelSelector="G" />
          </filter>
        </defs>
      </svg>
      <WebGLLayer vfxJs={sceneVfxJs} view={view} worldClick={worldClick} />
      {view.domVisible && <div
        className="canvas-world"
        style={{
          transform: `translate(${view.offsetX}px, ${view.offsetY}px) scale(${view.zoom})`,
          transformOrigin: '0 0',
        }}
      >
        {Array.from(agents.values()).filter(a => !a.is_container).map((agent) => (
            <div
              key={agent.id}
              className={`agent-wrapper${agent.id === activeAgentId ? ' agent-active' : ''}`}
              style={{
                left: Math.round(agent.x),
                top: Math.round(agent.y),
                width: Math.round(agent.width),
                height: Math.round(agent.height),
              }}
            >
              <AgentShape
                agent={agent}
                onDragStart={handleDragStart}
                send={send}
                subscribe={subscribe}
                readonly={isViewer}
                zoom={view.zoom}
              />
              {/* Resize edge handles */}
              <div className="agent-resize-edge agent-resize-top" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'top', e) }} />
              <div className="agent-resize-edge agent-resize-right" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'right', e) }} />
              <div className="agent-resize-edge agent-resize-bottom" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'bottom', e) }} />
              <div className="agent-resize-edge agent-resize-left" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'left', e) }} />
              {/* Resize corner handles */}
              <div className="agent-resize-corner agent-resize-tl" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'top-left', e) }} />
              <div className="agent-resize-corner agent-resize-tr" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'top-right', e) }} />
              <div className="agent-resize-corner agent-resize-bl" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'bottom-left', e) }} />
              <div className="agent-resize-corner agent-resize-br" onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); handleResizeStart(agent.id, 'bottom-right', e) }} />
            </div>
          ))}

      </div>}

      {/* Broadcast LIVE badge */}
      {isViewer && (
        <div style={{
          position: 'fixed', top: 16, right: 16, zIndex: 9999,
          background: '#ef4444', color: '#fff', padding: '6px 16px',
          borderRadius: 8, fontWeight: 700, fontSize: 14, letterSpacing: 1,
          boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
        }}>
          LIVE
        </div>
      )}
    </div>
  )
}
