import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import '@bundles/terminal/plugin'          // Side-effect: registers terminal plugin
import '@bundles/html/plugin'              // Side-effect: registers html plugin
import '@bundles/fantastic_agent/plugin'   // Side-effect: registers fantastic agent plugin

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
