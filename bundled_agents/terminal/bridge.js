/**
 * Terminal bundle bridge — xterm.js (CDN globals) + postMessage ↔ parent.
 */
(function() {
  var Terminal = window.Terminal;
  var FitAddon = window.FitAddon.FitAddon;
  var Unicode11Addon = window.Unicode11Addon.Unicode11Addon;

  var term = new Terminal({
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
  });

  var fit = new FitAddon();
  var unicode11 = new Unicode11Addon();
  term.loadAddon(fit);
  term.loadAddon(unicode11);
  term.unicode.activeVersion = '11';

  var container = document.getElementById('terminal');
  term.open(container);

  // Input → parent
  term.onData(function(data) {
    parent.postMessage({ type: 'input', data: data }, '*');
  });

  // Resize → parent
  term.onResize(function(size) {
    parent.postMessage({ type: 'resize', cols: size.cols, rows: size.rows }, '*');
  });

  // Parent → terminal
  window.addEventListener('message', function(e) {
    var msg = e.data;
    if (!msg || !msg.type) return;

    switch (msg.type) {
      case 'stream':
        term.write(msg.data);
        break;
      case 'clear':
        term.clear();
        break;
      case 'scroll_bottom':
        term.scrollToBottom();
        break;
      case 'config':
        if (msg.theme) {
          term.options.theme = Object.assign({}, term.options.theme, msg.theme);
        }
        break;
    }
  });

  // Fit on resize
  var fitTimer;
  var observer = new ResizeObserver(function() {
    clearTimeout(fitTimer);
    fitTimer = setTimeout(function() {
      fit.fit();
    }, 50);
  });
  observer.observe(container);

  // Initial fit + ready signal
  requestAnimationFrame(function() {
    fit.fit();
    parent.postMessage({ type: 'ready', cols: term.cols, rows: term.rows }, '*');
  });
})();
