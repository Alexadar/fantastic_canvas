# Serving a view package — the weak-binding recipe

**The host must not know this package exists.** Client↔server is a *weak
binding* (same rule as `kernel_bridge`: addressed by URL + path only, no shared
types). The Python `web` bundle is a generic static host; it serves whatever
`file` agents an operator (or an LLM following this recipe) wires
up. Nothing in `python/` references `ts/`. That decoupling is the point — and it
means **the same recipe serves any view package** (this TS kernel, a different
framework's `dist/`, a plain HTML app): point a `file` agent at its build output
and let it serve the static mount page from there too.

One duck-typed alias in `web/host/src/web/app.py` does all the work:

| alias | route | what answers it |
|---|---|---|
| `read{path}` | `GET /{id}/file/{path}` | a `file` agent → static file server rooted at a dir |

## Recipe (this TS kernel)

```bash
# 0. build the ESM bundle (one pinned dep: typescript; tests need none)
cd ts && npm install && npm run build        # → ts/dist/*.js  (ES modules)

# 1. a GENERIC file agent rooted at the build output.
#    /ts_dist/file/<path> now serves every dist module; relative ESM imports
#    (./kernel/kernel.js, ./transport/bridge.js, …) resolve under it. The build
#    also emits a static index.html mount page into ts/dist, served the same way.
fantastic fs_loader create_agent handler_module=file.tools id=ts_dist root=/ABS/PATH/TO/ts/dist
```

Open **`/ts_dist/file/index.html`** — the static mount page in `ts/dist`. It
loads `hello.js`, which `new WsBridge(...)`s to `/fs_loader/ws`, reflects the
kernel, and renders the live tree. The host never learned what `hello.js` is;
it's just bytes served by the `file` agent.

```html
<!doctype html><html><head><meta charset="utf-8"><title>fantastic · ts</title></head>
<body><script type="module" src="/ts_dist/file/hello.js"></script></body></html>
```

### The canvas mount page (with vendored three/xterm)

`main.js` is the canvas bootstrap; `hello.js` is the no-canvas starter — both
emitted by the same build and, alongside their static mount pages, served by the
same `file` agent. The canvas boots against the host's **`web_loader` alias** (a
`web/fs_loader` the operator created — see the root readme "Two kernels"): it
hydrates its OWN member tree from `.fantastic/web/` and persists changes back —
**no per-page `upstream`/session config**. The page needs only (a) an **import
map** binding the bare `three`/`@xterm/*` specifiers to the vendored files, and
(b) the xterm stylesheet. All vendored bytes serve from `…/file/vendor/`
(hermetic, no CDN — see `src/vendor/VENDOR.md`). `html_agent` iframe panels need
NO served bridge: the canvas injects a `fantastic` connector into each panel's
srcdoc that reaches the JS kernel via `postMessage` only (the kernel does the
local-vs-host routing — frontend code never dials the host). This page lives as a
static `.html` inside `ts/dist`:

```html
<!doctype html><html><head><meta charset="utf-8"><title>fantastic · canvas</title>
<link rel="stylesheet" href="/ts_dist/file/vendor/xterm.css">
<script type="importmap">{ "imports": {
  "three": "/ts_dist/file/vendor/three.module.js",
  "@xterm/xterm": "/ts_dist/file/vendor/xterm.js",
  "@xterm/addon-fit": "/ts_dist/file/vendor/addon-fit.js"
}}</script>
</head><body>
<script type="module" src="/ts_dist/file/main.js"></script>
</body></html>
```

Prereq: the operator created the `web_loader` store (`fantastic <web>
create_agent handler_module=fs_loader.tools root=.fantastic/web watch=false
alias=web_loader`). Heavy vendor loads lazily — `three` only when a `gl_view`
mounts, xterm only when a terminal opens — so the canvas shell stays light.

## Same trick, other views

Nothing above is TS-specific. To serve view package *X*:

1. build it to some `X/dist` (emit a static mount `index.html` into it),
2. `file` agent rooted at `X/dist` → its assets *and* its mount page are served,
3. open that mount page over `/<file_id>/file/<path>`; it loads `X`'s entry from
   the same `/file/` root.

The host stays a dumb static server; each view package is self-contained and
swappable. Weak binding is the beauty.
