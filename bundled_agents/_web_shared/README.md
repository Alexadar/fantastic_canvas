# _web_shared — transport protocol

The web bundle serves `dist/transport.js` at `/_fantastic/transport.js` and
injects it as the first `<script>` in every agent HTML page. UI code calls the
injected global `fantastic_transport()` to get a handle.

## Files

- `transport.ts` — **source of truth** (TypeScript).
- `dist/transport.js` — **build output** (generated, gitignored). Served by web bundle.
- `README.md` — this file.

## Build

```sh
cd bundled_agents/canvas/web
npm install
npm run build:transport          # produces ../../_web_shared/dist/transport.js
# or run with main build:
npm run build                    # builds canvas web + transport
```

`build:transport` uses `esbuild` to produce an IIFE bundle targeting ES2018.

## Usage (any agent HTML page)

```html
<!-- Transport is injected automatically; no import needed -->
<script>
  const t = fantastic_transport()
  const d = t.dispatcher

  // Dispatch: symmetric with backend. Same names, same args.
  const state = await d.get_state()
  await d.create_agent({ template: 'terminal' })

  // Events (async push from bus)
  t.on('agent_created', a => console.log(a))
  t.onAny((event, data) => console.log(event, data))
  await t.watch('ollama_abc')    // mirror another agent's events
</script>
```

## LLM-generated UIs

`fantastic_transport().description()` returns a self-contained spec (message
shapes, examples, `howToUse`) so an LLM can write a full agent UI in plain
HTML+JS with zero build step — only `<script src="/_fantastic/transport.js">`.

## Rule

`t.dispatch(name, args)` on the frontend ≡ `_DISPATCH[name](**args)` on the
backend. No aliasing. Discover names via `await d.get_handbook()`.
