import type { CanvasPlugin, CanvasContext } from './types'
import type { CanvasAgent } from '../types'

type Cleanup = () => void

class PluginRegistry {
  private plugins: CanvasPlugin[] = []

  register(plugin: CanvasPlugin) {
    this.plugins.push(plugin)
  }

  /** Canvas calls this in useEffect — all plugins inject into canvas DOM. */
  injectAll(dom: HTMLElement, ctx: CanvasContext): Cleanup {
    const cleanups = this.plugins
      .map(p => p.injectCanvas?.(dom, ctx))
      .filter(Boolean) as Cleanup[]
    return () => cleanups.forEach(fn => fn())
  }

  /** AgentShape calls this — find matching plugin for an agent. */
  findPlugin(agent: CanvasAgent): CanvasPlugin | null {
    for (const p of this.plugins) {
      if (p.matchAgent?.(agent)) return p
    }
    return null
  }
}

export const registry = new PluginRegistry()
