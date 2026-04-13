import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import '@bundles/terminal/plugin'          // Side-effect: registers terminal plugin
import '@bundles/html/plugin'              // Side-effect: registers html plugin
import '@bundles/fantastic_agent/plugin'   // UI proxy for AI backends
// AI bundles (ollama/openai/anthropic/integrated) are headless.
// They render via web bundle at /{agent_id}/ and are fronted by fantastic_agent.

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
