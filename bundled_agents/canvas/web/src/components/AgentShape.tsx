import { useCallback, useEffect, useRef, useState } from 'react'
import type { CanvasAgent, TransportMessage } from '../types'
import { HtmlAgentBody } from './base'
import { registry } from '../plugins/registry'

interface AgentShapeProps {
  agent: CanvasAgent
  onDragStart: (agentId: string, x: number, y: number, e: React.MouseEvent) => void
  send: (msg: TransportMessage) => void
  subscribe: (fn: (msg: TransportMessage) => void) => () => void
  readonly?: boolean
  zoom?: number
}

export function AgentShape({
  agent,
  onDragStart,
  send,
  subscribe,
  readonly = false,
  zoom = 1,
}: AgentShapeProps) {
  const plugin = registry.findPlugin(agent)
  const hasHtmlContent = !!(agent.html_content || agent.output_html)
  const showPluginBody = !!plugin?.injectAgent
  const showHtmlBody = !showPluginBody && hasHtmlContent
  const chromeless = plugin?.chromeless ?? false

  // Header label
  const headerLabel = agent.display_name || plugin?.name || 'Agent'
  const accentColor = plugin?.accentColor || '#666'

  // Refresh key — incrementing forces iframe-based agents to reload
  const localRefreshRef = useRef(0)
  const [localRefresh, setLocalRefresh] = useState(0)
  const refreshKey = (agent._refreshKey || 0) + localRefresh

  // Plugin injection into agent header (extra buttons)
  const headerExtraRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!headerExtraRef.current || !plugin?.injectHeader) return
    return plugin.injectHeader(headerExtraRef.current, { agent, send, subscribe })
  }, [agent.id, agent.bundle])

  // Plugin injection into agent body
  const bodyRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!bodyRef.current || !plugin?.injectAgent) return
    return plugin.injectAgent(bodyRef.current, { agent, send, subscribe })
  }, [agent.id, agent.bundle])

  const handleHeaderMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0 || e.altKey || e.ctrlKey || e.metaKey) return
    if ((e.target as HTMLElement).closest('button, label, input')) return
    onDragStart(agent.id, agent.x, agent.y, e)
  }

  const locked = !!agent.delete_lock

  const handleClose = () => {
    if (locked) return
    send({ type: 'delete_agent', agent_id: agent.id })
  }

  const handleToggleLock = useCallback(() => {
    send({ type: 'update_agent', agent_id: agent.id, options: { delete_lock: !agent.delete_lock } })
  }, [agent.id, agent.delete_lock, send])

  const handleRefresh = useCallback(() => {
    if (plugin?.onRefresh) {
      plugin.onRefresh(agent.id, { send })
    }
    if (showHtmlBody) {
      localRefreshRef.current += 1
      setLocalRefresh(localRefreshRef.current)
    }
  }, [plugin, agent.id, send, showHtmlBody])

  return (
    <div
      className={`agent-shape${chromeless ? ' agent-chromeless' : ''}`}
    >
      {/* Glass layers — behind all content */}
      <div className="agent-glass-effect" />
      <div className={`agent-glass-tint${showPluginBody ? ' agent-glass-tint--terminal' : ''}`} />
      <div className="agent-glass-shine" />

      {/* Header — drag handle */}
      <div
        className={`agent-header agent-drag-handle${chromeless ? ' agent-chrome' : ''}`}
        onMouseDown={handleHeaderMouseDown}
      >
        <div className="agent-header-accent" style={{ backgroundColor: accentColor }} />
        <span className="agent-header-label">{headerLabel}</span>
        <div className="agent-header-right">
          {!readonly && plugin?.injectHeader && (
            <div ref={headerExtraRef} style={{ display: 'contents' }} />
          )}
          {!readonly && (
            <>
              <button
                className={`agent-header-btn${locked ? ' agent-header-btn--locked' : ''}`}
                onClick={handleToggleLock}
                title={locked ? 'Unlock deletion' : 'Lock deletion'}
              >
                {locked ? '\u{1F512}' : '\u{1F513}'}
              </button>
              <button
                className="agent-header-btn"
                onClick={handleRefresh}
                title="Refresh agent"
              >
                &#x21bb;
              </button>
              <button
                className="agent-close-btn"
                onClick={handleClose}
                title={locked ? 'Deletion locked' : 'Close agent'}
                disabled={locked}
              >
                &times;
              </button>
            </>
          )}
        </div>
      </div>

      {/* Plugin-injected body (terminal bundles etc.) */}
      {showPluginBody && (
        <div className="agent-body agent-bundle-body" ref={bodyRef} />
      )}

      {/* HTML content body */}
      {showHtmlBody && (
        <HtmlAgentBody key={refreshKey} html={agent.html_content || agent.output_html || ''} />
      )}
    </div>
  )
}
