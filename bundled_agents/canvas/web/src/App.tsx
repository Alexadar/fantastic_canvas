import { Canvas } from './components/Canvas'
import './styles.css'

/**
 * Canvas is served at `/{canvas_agent_id}/` by the web bundle.
 * Ask the injected transport for the agent id — no URL parsing in UI code.
 */
function getCanvasAgentId(): string {
  try {
    return (window as any).fantastic_transport?.().agentId ?? ''
  } catch {
    return ''
  }
}

export default function App() {
  return <Canvas canvasName={getCanvasAgentId()} />
}
