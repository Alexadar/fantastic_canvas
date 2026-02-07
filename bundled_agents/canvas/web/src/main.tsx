import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import '@bundles/terminal/plugin'  // Side-effect: registers terminal plugin
import '@bundles/html/plugin'      // Side-effect: registers html plugin

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
