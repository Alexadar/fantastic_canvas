/**
 * Terminal bundle bridge — xterm.js + postMessage ↔ parent window.
 *
 * Runs inside an iframe. Communicates with the parent (canvas plugin)
 * via postMessage:
 *
 * iframe → parent:
 *   { type: 'ready', cols, rows }
 *   { type: 'input', data }
 *   { type: 'resize', cols, rows }
 *
 * parent → iframe:
 *   { type: 'stream', data }
 *   { type: 'clear' }
 *   { type: 'config', theme }
 */

import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { Unicode11Addon } from '@xterm/addon-unicode11'

const term = new Terminal({
  cursorBlink: true,
  fontSize: 13,
  fontFamily: "'SF Mono', 'Fira Code', 'Cascadia Code', monospace",
  allowProposedApi: true,
  allowTransparency: true,
  theme: {
    background: '#00000000',
    foreground: '#e5e5e5',
    cursor: '#e5e5e5',
    selectionBackground: '#3b82f640',
  },
})

const fit = new FitAddon()
const unicode11 = new Unicode11Addon()
term.loadAddon(fit)
term.loadAddon(unicode11)
term.unicode.activeVersion = '11'

// Mount terminal
const container = document.getElementById('terminal')!
term.open(container)

// Input → parent
term.onData((data) => {
  parent.postMessage({ type: 'input', data }, '*')
})

// Resize → parent
term.onResize(({ cols, rows }) => {
  parent.postMessage({ type: 'resize', cols, rows }, '*')
})

// Parent → terminal
window.addEventListener('message', (e) => {
  const msg = e.data
  if (!msg || !msg.type) return

  switch (msg.type) {
    case 'stream':
      term.write(msg.data)
      break
    case 'clear':
      term.clear()
      break
    case 'scroll_bottom':
      term.scrollToBottom()
      break
    case 'config':
      if (msg.theme) {
        term.options.theme = { ...term.options.theme, ...msg.theme }
      }
      break
  }
})

// Fit on resize
let fitTimer: ReturnType<typeof setTimeout> | undefined
const observer = new ResizeObserver(() => {
  clearTimeout(fitTimer)
  fitTimer = setTimeout(() => {
    fit.fit()
  }, 50)
})
observer.observe(container)

// Initial fit + ready signal
requestAnimationFrame(() => {
  fit.fit()
  parent.postMessage({ type: 'ready', cols: term.cols, rows: term.rows }, '*')
})
