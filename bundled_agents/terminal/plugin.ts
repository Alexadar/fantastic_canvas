import { registry } from '@bundles/canvas/web/src/plugins/registry'
import type { CanvasPlugin, AgentContext } from '@bundles/canvas/web/src/plugins/types'
import type { WSMessage } from '@bundles/canvas/web/src/types'

export const terminalPlugin: CanvasPlugin = {
  name: 'terminal',
  accentColor: '#666',

  matchAgent: (agent) => agent.bundle === 'terminal',

  onRefresh: (agentId, { send }) => {
    send({ type: 'process_restart', agent_id: agentId })
  },

  // Autoscroll toggle in header
  injectHeader: (dom, ctx) => {
    const btn = document.createElement('button')
    btn.className = 'agent-header-btn'
    btn.title = 'Toggle autoscroll'
    btn.textContent = '⇣'
    btn.style.opacity = '0.5'
    dom.appendChild(btn)

    let active = false
    let timer: ReturnType<typeof setInterval> | null = null

    const getIframe = () =>
      btn.closest('.agent-shape')?.querySelector('iframe') as HTMLIFrameElement | null

    const start = () => {
      active = true
      btn.style.opacity = '1'
      btn.style.background = 'rgba(255,255,255,0.15)'
      timer = setInterval(() => {
        getIframe()?.contentWindow?.postMessage({ type: 'scroll_bottom' }, '*')
      }, 100)
    }

    const stop = () => {
      active = false
      btn.style.opacity = '0.5'
      btn.style.background = ''
      if (timer) { clearInterval(timer); timer = null }
    }

    btn.addEventListener('click', (e) => {
      e.stopPropagation()
      active ? stop() : start()
    })

    return () => { stop(); btn.remove() }
  },

  // Inject into canvas: own double-click handler
  injectCanvas: (dom, ctx) => {
    const handler = (e: MouseEvent) => {
      // Ignore clicks on agents
      if ((e.target as HTMLElement).closest('.agent-wrapper')) return
      const { x, y } = ctx.screenToCanvas(e)
      ctx.send({ type: 'create_agent', template: 'terminal', options: { x, y } })
    }
    dom.addEventListener('dblclick', handler)
    return () => dom.removeEventListener('dblclick', handler)
  },

  // Inject into agent body: iframe + postMessage bridge
  injectAgent: (dom, ctx) => {
    const iframe = document.createElement('iframe')
    iframe.src = `/bundles/terminal/index.html`
    iframe.style.cssText = 'width:100%;height:100%;border:none;background:transparent'
    iframe.setAttribute('allowTransparency', 'true')
    dom.appendChild(iframe)

    let iframeReady = false

    // iframe → parent → WS
    const onMessage = (e: MessageEvent) => {
      if (e.source !== iframe.contentWindow) return
      const msg = e.data
      if (!msg || !msg.type) return

      switch (msg.type) {
        case 'ready':
          iframeReady = true
          // Connect to backend process (creates or reconnects)
          ctx.send({
            type: 'process_create',
            agent_id: ctx.agent.id,
            cols: msg.cols,
            rows: msg.rows,
          })
          break
        case 'input':
          ctx.send({
            type: 'process_input',
            agent_id: ctx.agent.id,
            data: msg.data,
          })
          break
        case 'resize':
          ctx.send({
            type: 'process_resize',
            agent_id: ctx.agent.id,
            cols: msg.cols,
            rows: msg.rows,
          })
          break
      }
    }
    window.addEventListener('message', onMessage)

    // WS → parent → iframe
    const unsub = ctx.subscribe((msg: WSMessage) => {
      if (!iframeReady) return
      const aid = msg.agent_id as string
      if (aid !== ctx.agent.id) return

      switch (msg.type) {
        case 'process_output':
          iframe.contentWindow?.postMessage({ type: 'stream', data: msg.data }, '*')
          break
        case 'process_closed':
          iframe.contentWindow?.postMessage({ type: 'clear' }, '*')
          break
      }
    })

    return () => {
      window.removeEventListener('message', onMessage)
      unsub()
      iframe.remove()
    }
  },
}

registry.register(terminalPlugin)
