# Fantastic Canvas

You have access to an infinite spatial canvas at `{{SERVER_URL}}`.

**Transport: WebSocket only.** Every agent has its own URL and WS channel at
`{{SERVER_URL}}/{agent_id}/ws`. HTTP is only used to fetch the HTML page that
brings in the injected `fantastic_transport()` global.

From any agent HTML served by the web bundle:

```js
const t = fantastic_transport()          // injected global — zero imports
const d = t.dispatcher                    // Proxy — dispatcher.NAME(args) ≡ _DISPATCH[NAME](**args)

await d.list_agents()
await d.create_agent({ template: 'terminal', options: { x: 100, y: 100 } })
await d.execute_python({ agent_id: 'terminal_abc', code: 'print(40+2)' })
t.on('agent_created', a => console.log(a))
await t.watch('ollama_xyz')               // mirror another agent's events
```

No REST. No `/api/call`. No `fetch()`. Just the transport.

Runtime self-documentation: `fantastic_transport().description()` returns a JSON
spec (message shapes, examples, markdown guide) — introspect when unsure.

## Writing an HTML agent page

Minimal template any agent bundle can ship as `web/index.html`. The web bundle
injects `<script src="/_fantastic/transport.js">` automatically, so nothing to import:

```html
<!DOCTYPE html>
<html><body>
<div id="out"></div>
<script>
  const t = fantastic_transport()
  const d = t.dispatcher
  const out = document.getElementById('out')

  // Symmetric dispatch (maps to backend _DISPATCH[name](**args))
  const agents = await d.list_agents()
  out.textContent = JSON.stringify(agents, null, 2)

  // Errors come back as rejected promises — catch or check .error
  try { await d.delete_agent({ agent_id: 'nope' }) }
  catch (e) { console.warn('delete failed:', e.message) }

  // Subscribe to events routed to THIS agent's inbox
  t.on('agent_created', a => console.log('new:', a))
  t.onAny((event, data) => console.log(event, data))

  // Mirror another agent's events into my inbox (e.g. to watch an AI stream)
  await t.watch('ollama_abc123')
  t.on('ollama_response', chunk => out.append(chunk.text || ''))
</script>
</body></html>
```

## Events (backend → frontend, via `t.on(name, handler)`)

| Event | Payload | When |
|---|---|---|
| `agent_created` | `{agent: {id, bundle, ...}}` | `create_agent` succeeded |
| `agent_moved` | `{agent_id, x, y}` | `move_agent` |
| `agent_resized` | `{agent_id, width, height}` | `resize_agent` |
| `agent_updated` | `{agent_id, ...fields}` | `update_agent` / configure |
| `agent_deleted` | `{agent_id}` | `delete_agent` |
| `agent_output` | `{agent_id, html}` | `post_output` |
| `agent_refresh` | `{agent_id}` | `refresh_agent` |
| `process_output` | `{agent_id, data}` | PTY stdout chunk |
| `process_closed` | `{agent_id, code}` | PTY exited |
| `process_started` | `{agent_id, pid}` | PTY spawned |
| `{bundle}_response` | `{agent_id, text, done}` | AI streaming (per ollama/openai/...) |
| `{bundle}_state` | `{agent_id, state}` | AI state: thinking/responding/idle |
| `{bundle}_error` | `{agent_id, error}` | AI failure |
| `{bundle}_history_response` | `{agent_id, messages}` | Reply to `{bundle}_history` |
| `context_usage` | `{agent_id, used, max, provider, provider_online, schedules, total_runs}` | After each AI response |
| `scene_vfx_updated` | `{js, canvas_name}` | Canvas VFX changed |
| `scene_vfx_data` | `{data, canvas_name}` | Canvas VFX runtime state |

## Argument signatures (the most common ones)

Exhaustive reference: `await d.get_handbook()`. Quick cheat sheet:

```js
d.create_agent({ template: 'terminal', parent?, options: { x, y, width, height } })
d.list_agents({ parent: '' })                 // parent='' = all
d.read_agent({ agent_id })
d.update_agent({ agent_id, options: { display_name?, autostart?, delete_lock? } })
d.delete_agent({ agent_id })
d.move_agent({ agent_id, x, y })
d.resize_agent({ agent_id, width, height })
d.post_output({ agent_id, html })
d.execute_python({ agent_id, code })
d.agent_call({ target_agent_id, verb, ...args })  // universal RPC; verb default "send"
// File ops (file bundle): go through agent_call
d.agent_call({ target_agent_id: '<file_hex>', verb: 'list', path: '' })
d.agent_call({ target_agent_id: '<file_hex>', verb: 'read', path: 'CLAUDE.md' })
d.agent_call({ target_agent_id: '<file_hex>', verb: 'write', path: 'x.txt', content: '...' })
// Content aliases (via web bundle): agent_call on the web agent
d.agent_call({ target_agent_id: '<web_hex>', verb: 'alias', kind: 'file', path: '…' })
d.agent_call({ target_agent_id: '<web_hex>', verb: 'alias', kind: 'url',  url:  'https://…' })
d.process_input({ agent_id, data })
d.process_resize({ agent_id, cols, rows })
d.terminal_output({ agent_id, max_lines: 200 })
// Scheduling (scheduler bundle): agent_call on a scheduler agent
d.agent_call({ target_agent_id: '<scheduler_hex>', verb: 'schedule',
               for_agent_id, action: { type: 'tool'|'prompt', ... }, interval_seconds })
// Every fire emits: t.on('schedule_fired', (evt) => ...)
d.web_configure({ agent_id, port?, base_route? })     // hot-reloads uvicorn
d.ollama_send({ agent_id, text })              // and openai_, anthropic_, integrated_
d.fantastic_agent_configure({ agent_id, upstream_agent_id, upstream_bundle })
```

Replies return the underlying `ToolResult.data`. On failure the promise rejects
with the backend error message. Some tools also return `{error: "..."}` inside
`.data` for recoverable cases — check both.

## Typical bootstrap

```
# From CLI:
fantastic add canvas
fantastic add terminal
fantastic add ollama              # headless AI backend
fantastic add fantastic_agent     # chat UI proxy
fantastic                         # start engine + web

# Then from any agent page or external client:
await d.fantastic_agent_configure({
  agent_id: '<fa_id>',
  upstream_agent_id: '<ollama_id>',
  upstream_bundle: 'ollama',
})
# Open http://localhost:8888/<fa_id>/ → chat UI ready
```

## Python helper (from outside browser — admin / CLI)

Use a WS client that speaks the protocol (see `core/protocol.py`). Minimal example:

```python
import asyncio, json, uuid, websockets

async def call(agent_id, tool, **args):
    async with websockets.connect(f"ws://localhost:8888/{agent_id}/ws") as ws:
        req_id = str(uuid.uuid4())
        await ws.send(json.dumps({"type": "call", "tool": tool, "args": args, "id": req_id}))
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == req_id:
                return msg["data"] if msg["type"] == "reply" else msg["error"]

asyncio.run(call("web_main", "list_agents"))
```

## Complete tool catalog

Every name below maps 1:1 on the frontend as `d.{name}(args)`.

**Agents**: `create_agent`, `list_agents`, `read_agent`, `delete_agent`, `rename_agent`, `update_agent`, `refresh_agent`, `post_output`
**Execution**: `execute_python`, `agent_run`
**State**: `get_state`, `get_full_state`
**Canvas layout**: `move_agent`, `resize_agent`, `scene_vfx`, `scene_vfx_data`, `spatial_discovery`
**Process (PTY)**: `process_create`, `process_input`, `process_resize`, `process_close`, `process_attach`, `process_enter`, `process_output`, `process_restart`, `process_signal`
**Terminal shortcuts**: `terminal_output`, `terminal_restart`, `terminal_signal`
**Files** (`file` bundle): `add file name=…` creates a file-root agent. Verbs via `agent_call verb=list|read|write|delete|rename|mkdir`. Internal handler names: `file_list`, `file_read`, `file_write`, `file_delete`, `file_rename`, `file_mkdir`.
**Content aliases** (web bundle): `agent_call verb=alias|aliases|unalias` on any web agent. Served at `GET /content/{alias_id}`. Internal handler names: `web_alias`, `web_aliases`, `web_unalias`.
**Inter-agent**: `agent_call`
**Memory**: `read_agent_memory`, `append_agent_memory`
**Schedules** (`scheduler` bundle): `add scheduler name=…` creates a scheduler agent. Verbs via `agent_call verb=schedule|unschedule|list|pause|resume|tick_now|history`. Internal handler names: `scheduler_schedule`, `scheduler_unschedule`, `scheduler_list`, `scheduler_pause`, `scheduler_resume`, `scheduler_tick_now`, `scheduler_history`. Every fire emits a `schedule_fired` event.
**Web transport**: `web_configure` (change port / base_route; hot-reloads uvicorn)
**Connected instances** (`instance` bundle): `add instance` creates an instance agent (transport `ws` or `ssh`). Verbs via `agent_call verb=start|stop|status|call`. Internal handler names: `instance_start`, `instance_stop`, `instance_status`, `instance_call`.
**Conversation log**: `conversation_log`, `conversation_say`, `core_chat_message`
**AI (per bundle ollama/openai/anthropic/integrated)**: `{bundle}_send`, `{bundle}_interrupt`, `{bundle}_save_message`, `{bundle}_history`, `{bundle}_configure`
**fantastic_agent**: `fantastic_agent_get_config`, `fantastic_agent_configure`, `fantastic_agent_save_message`, `fantastic_agent_history`
**Handbook**: `get_handbook`, `get_handbook_canvas`, `get_handbook_terminal`, `list_templates`, `register_template`, `server_logs`

## How to use this file

```bash
cat .fantastic/fantastic.md | claude
cat .fantastic/fantastic.md | gemini
cat .fantastic/fantastic.md | codex -
```

## Best practices

- **Never inline base64 in `post_output`** — payloads over 512KB crash the canvas. Use `agent_call(web_id, verb="alias", kind="file", path=…)` → serve at `/content/{alias_id}`.
- **Large assets** (images, CSVs, plots): always save to project dir → `agent_call verb=alias` on the web agent → URL in HTML.
- **UI code uses ONLY `fantastic_transport()`**. No `fetch`, no `/api/...` URLs, no `new WebSocket(...)`.
- **Agent IDs follow `{bundle}_{hex6}`** (e.g. `terminal_a3f2b1`). Bundle is mandatory when creating.
- **AI providers are bundled agents** — `fantastic add ollama` creates a backend; `fantastic add fantastic_agent` gives it a chat UI. Configure with `fantastic_agent_configure(agent_id, upstream_agent_id, upstream_bundle)`.

## Key facts

- **Agent types**: `terminal`, `html`, `canvas`, `fantastic_agent`, AI bundles (ollama/openai/anthropic/integrated), `web`, `quickstart`
- **Python execution** is stateless (subprocess per call), recorded in agent memory (`memory_long.jsonl`)
- **Agent memory** at `.fantastic/agents/{id}/memory_long.jsonl` — access via `read_agent_memory`/`append_agent_memory` dispatches
- **Project files** live in the project root; agent state in `.fantastic/agents/{id}/`
- **Skill deep-dives**: `get_handbook_canvas`, `get_handbook_terminal`
- **Multiple web agents**: add more with `fantastic add web` + `web_configure(port, base_route)` for separate ports/paths
