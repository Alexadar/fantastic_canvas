export interface CanvasAgent {
  id: string
  bundle?: string           // "terminal" | custom | undefined
  parent?: string           // parent agent ID (e.g. canvas agent)
  display_name: string
  x: number
  y: number
  width: number
  height: number
  output_html: string
  delete_lock?: boolean
  url?: string
  html_content?: string
  is_container?: boolean    // spatial container (e.g. canvas) — not rendered as a shape
  has_iframe?: boolean      // renders HTML content in an iframe
  _refreshKey?: number
}

export interface WSMessage {
  type: string
  [key: string]: unknown
}
