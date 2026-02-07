import type { CanvasAgent, WSMessage } from '../types'

export type SendFn = (msg: WSMessage) => void
export type SubscribeFn = (fn: (msg: WSMessage) => void) => () => void
type Cleanup = () => void

export interface CanvasContext {
  send: SendFn
  subscribe: SubscribeFn
  screenToCanvas: (e: MouseEvent) => { x: number; y: number }
}

export interface AgentContext {
  agent: CanvasAgent
  send: SendFn
  subscribe: SubscribeFn
}

export interface CanvasPlugin {
  name: string
  matchAgent?: (agent: CanvasAgent) => boolean
  injectCanvas?: (dom: HTMLElement, ctx: CanvasContext) => Cleanup
  injectAgent?: (dom: HTMLElement, ctx: AgentContext) => Cleanup
  /** Inject extra controls into agent header (right side, before refresh/close) */
  injectHeader?: (dom: HTMLElement, ctx: AgentContext) => Cleanup
  /** Plugin handles its own refresh logic. Called when user clicks refresh button. */
  onRefresh?: (agentId: string, ctx: { send: SendFn }) => void
  /** Accent color for header bar. Default: '#666' */
  accentColor?: string
  /** If true, agent shape gets chromeless styling */
  chromeless?: boolean
}
