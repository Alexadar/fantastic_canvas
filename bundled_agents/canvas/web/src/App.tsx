import { Canvas } from './components/Canvas'
import './styles.css'

/** Extract canvas name from /canvas/{name} URL path. */
function getCanvasName(): string {
  const match = window.location.pathname.match(/^\/canvas\/([^/]+)/)
  return match ? match[1] : ''
}

export default function App() {
  const canvasName = getCanvasName()
  return <Canvas canvasName={canvasName} />
}
