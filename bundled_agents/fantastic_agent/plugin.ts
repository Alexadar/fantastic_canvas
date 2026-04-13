/**
 * fantastic_agent canvas plugin — LAYOUT ONLY.
 *
 * Content is served by the web bundle at /{agent_id}/ (see web/index.html).
 */
import { registry } from '@bundles/canvas/web/src/plugins/registry'
import type { CanvasPlugin } from '@bundles/canvas/web/src/plugins/types'

export const fantasticAgentPlugin: CanvasPlugin = {
  name: 'fantastic_agent',
  accentColor: '#4a3a8a',

  matchAgent: (agent) => agent.bundle === 'fantastic_agent',

  injectAgent: (dom, ctx) => {
    const iframe = document.createElement('iframe')
    iframe.src = `/${ctx.agent.id}/`
    iframe.style.cssText = 'width:100%;height:100%;border:none;background:transparent'
    iframe.setAttribute('allowTransparency', 'true')
    dom.appendChild(iframe)
    return () => iframe.remove()
  },
}

registry.register(fantasticAgentPlugin)
