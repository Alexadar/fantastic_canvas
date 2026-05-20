// fantastic_transport — minimal client for the kernel's HTTP+WS surface.
// Injected automatically on every served HTML page. Same API shape any
// frontend (the canvas webapp, ai_chat_webapp, browser dev consoles)
// consumes. Pure JS, no build step.

(function () {
  if (window.fantastic_transport) return;

  function fantastic_transport(opts) {
    opts = opts || {};
    // The path component before the trailing slash is the agent id this
    // page is rendered for — e.g. /canvas_1/ → "canvas_1".
    const m = location.pathname.match(/^\/([^\/]+)\//);
    const agentId = (opts.agentId || (m && m[1]) || "").trim();
    const wsUrl =
      opts.wsUrl ||
      (location.protocol === "https:" ? "wss://" : "ws://") +
        location.host +
        "/" +
        agentId +
        "/ws";

    let ws = null;
    let nextId = 1;
    const pending = new Map();
    const watchers = new Map(); // src_id -> callback
    const reopenDelayMs = 500;
    let closedByUser = false;

    function open() {
      ws = new WebSocket(wsUrl);
      ws.onmessage = (e) => {
        let msg;
        try {
          msg = JSON.parse(e.data);
        } catch (err) {
          return;
        }
        if (msg.type === "reply" && pending.has(msg.id)) {
          const { resolve } = pending.get(msg.id);
          pending.delete(msg.id);
          resolve(msg.data);
          return;
        }
        if (msg.type === "error" && pending.has(msg.id)) {
          const { reject } = pending.get(msg.id);
          pending.delete(msg.id);
          reject(new Error(msg.error || "unknown error"));
          return;
        }
        if (msg.type === "event") {
          const p = msg.payload || {};
          const fn = watchers.get(p.target);
          if (fn) fn(p);
          if (p.type === "reload_html") location.reload();
        }
      };
      ws.onclose = () => {
        if (!closedByUser) setTimeout(open, reopenDelayMs);
      };
      ws.onerror = () => {
        try {
          ws.close();
        } catch {}
      };
    }
    open();

    function call(target, payload) {
      return new Promise((resolve, reject) => {
        const id = String(nextId++);
        pending.set(id, { resolve, reject });
        const send = () =>
          ws.send(JSON.stringify({ type: "call", target, payload, id }));
        if (ws.readyState === 1) send();
        else ws.addEventListener("open", send, { once: true });
      });
    }

    function emit(target, payload) {
      const send = () =>
        ws.send(JSON.stringify({ type: "emit", target, payload }));
      if (ws.readyState === 1) send();
      else ws.addEventListener("open", send, { once: true });
    }

    function watch(src, cb) {
      watchers.set(src, cb);
      const send = () => ws.send(JSON.stringify({ type: "watch", src }));
      if (ws.readyState === 1) send();
      else ws.addEventListener("open", send, { once: true });
    }

    function unwatch(src) {
      watchers.delete(src);
      try {
        ws.send(JSON.stringify({ type: "unwatch", src }));
      } catch {}
    }

    function close() {
      closedByUser = true;
      try {
        ws.close();
      } catch {}
    }

    const bus = new BroadcastChannel("fantastic");

    return {
      agentId,
      call,
      emit,
      watch,
      unwatch,
      close,
      bus,
    };
  }

  window.fantastic_transport = fantastic_transport;
})();
