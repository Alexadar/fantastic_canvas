/**
 * Terminal canvas plugin — LAYOUT ONLY.
 *
 * Content is served by the web bundle at /{agent_id}/. We just embed it as
 * an iframe; the terminal page uses fantastic_transport() directly (no WS here).
 *
 * Autoscroll + robot button are still injected into the canvas header.
 */

import { registry } from '@bundles/canvas/web/src/plugins/registry'
import type { CanvasPlugin } from '@bundles/canvas/web/src/plugins/types'

export const terminalPlugin: CanvasPlugin = {
  name: 'terminal',
  accentColor: '#666',

  matchAgent: (agent) => agent.bundle === 'terminal',

  onRefresh: (agentId, { send }) => {
    send({ type: 'process_restart', agent_id: agentId })
  },

  injectHeader: (dom, ctx) => {
    // Autoscroll toggle (persisted to agent.json via update_agent)
    const btn = document.createElement('button')
    btn.className = 'agent-header-btn'
    btn.title = 'Toggle autoscroll'
    btn.textContent = '⇣'
    dom.appendChild(btn)

    let active = false

    const getIframe = () =>
      btn.closest('.agent-shape')?.querySelector('iframe') as HTMLIFrameElement | null

    const applyStyle = () => {
      btn.style.opacity = active ? '1' : '0.5'
      btn.style.background = active ? 'rgba(255,255,255,0.15)' : ''
    }

    // Push the current flag into the iframe. Safe to call before iframe load —
    // we retry on its load event too.
    const pushFlag = () => {
      const w = getIframe()?.contentWindow as any
      if (w && w.__autoscroll) {
        w.__autoscroll.enabled = active
        if (active && typeof w.__scrollBottom === 'function') w.__scrollBottom()
      }
    }

    // Re-push when the iframe (re)loads — e.g. on process_restart.
    const iframe = getIframe()
    iframe?.addEventListener('load', pushFlag)

    const start = () => { active = true; applyStyle(); pushFlag() }
    const stop  = () => { active = false; applyStyle(); pushFlag() }

    if ((ctx.agent as any).autoscroll) start()
    else applyStyle()

    btn.addEventListener('click', (e) => {
      e.stopPropagation()
      active ? stop() : start()
      ctx.send({ type: 'update_agent', agent_id: ctx.agent.id, options: { autoscroll: active } })
    })

    // AI agent shortcut
    const aiBtn = document.createElement('button')
    aiBtn.className = 'agent-header-btn'
    aiBtn.title = 'Open AI agent'
    const img = document.createElement('img')
    img.src = '/favicon.png'
    img.style.cssText = 'width:14px;height:14px;vertical-align:middle;'
    aiBtn.appendChild(img)
    aiBtn.style.opacity = '0.5'
    dom.appendChild(aiBtn)

    aiBtn.addEventListener('click', (e) => {
      e.stopPropagation()
      ctx.send({
        type: 'create_agent',
        template: 'ollama',
        options: { x: ctx.agent.x + ctx.agent.width + 20, y: ctx.agent.y },
      })
    })

    return () => { stop(); btn.remove(); aiBtn.remove() }
  },

  // Dblclick on empty canvas → spawn terminal
  injectCanvas: (dom, ctx) => {
    const handler = (e: MouseEvent) => {
      if ((e.target as HTMLElement).closest('.agent-wrapper')) return
      const { x, y } = ctx.screenToCanvas(e)
      ctx.send({ type: 'create_agent', template: 'terminal', options: { x, y } })
    }
    dom.addEventListener('dblclick', handler)
    return () => dom.removeEventListener('dblclick', handler)
  },

  // Body: just iframe the agent's own URL — web bundle injects transport there.
  injectAgent: (dom, ctx) => {
    const iframe = document.createElement('iframe')
    iframe.src = `/${ctx.agent.id}/`
    iframe.style.cssText = 'width:100%;height:100%;border:none;background:transparent'
    iframe.setAttribute('allowTransparency', 'true')
    dom.appendChild(iframe)

    return () => {
      iframe.remove()
    }
  },
}

registry.register(terminalPlugin)
