import { registry } from '@bundles/canvas/web/src/plugins/registry'
import type { CanvasPlugin } from '@bundles/canvas/web/src/plugins/types'

export const htmlPlugin: CanvasPlugin = {
  name: 'HTML',
  accentColor: '#f59e0b',
  chromeless: true,

  matchAgent: (agent) =>
    agent.bundle === 'html' || !!(agent.html_content || agent.output_html),

  // No-op: AgentShape handles html refresh via iframe key remount
  onRefresh: () => {},
}

registry.register(htmlPlugin)
