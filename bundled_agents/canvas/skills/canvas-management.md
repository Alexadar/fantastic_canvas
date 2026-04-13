# Canvas Management

Agent lifecycle, layout, content aliases, and visual effects.

## Getting Started

```bash
fantastic add web          # transport bundle (auto-added on first run)
fantastic add canvas       # spatial host
fantastic                  # start
# Open http://localhost:8888/{canvas_agent_id}/
```

## Agent types on a canvas

| Bundle | Purpose | Default size |
|---|---|---|
| `terminal` | PTY shell (xterm) | 600×350 |
| `html` | Static HTML in iframe | 800×600 |
| `fantastic_agent` | Chat UI fronting an AI backend | 400×500 |
| `ollama`/`openai`/`anthropic`/`integrated` | Headless AI backends (no UI) | — |
| `canvas` | Another spatial host (nestable) | — |

## Dispatch (symmetric on frontend via `d.{name}(args)`)

### `create_agent({ template, parent?, options: {x, y, width, height}, url?, html_content? })`
Create agent. `template` = bundle name. Returns the full agent dict.
Directory auto-named `{template}_{hex6}`. Bundle is required (see conventions).

### `read_agent({ agent_id })`
Full agent state.

### `delete_agent({ agent_id })`
Delete. Respects `delete_lock`.

### `move_agent({ agent_id, x, y })` / `resize_agent({ agent_id, width, height })`
Reposition / resize.

### `rename_agent({ agent_id, display_name })` / `update_agent({ agent_id, options })`
Set display name / bulk property update (e.g. `{autostart, delete_lock, autoscroll}`).

### `refresh_agent({ agent_id })`
Restart terminal or reload iframe. Emits `process_closed`/`process_started` or `agent_refresh`.

### `spatial_discovery({ agent_id, radius? })`
Find nearby agents by rectangular distance.

## Code Execution

### `execute_python({ agent_id, code })`
Stateless subprocess. `cwd` = project dir — always use relative paths in code.

## Content Aliases

### `content_alias_file({ file_path, persistent: true })` → `{ alias_path: "/content/{id}" }`
### `content_alias_url({ url, persistent: true })` → `{ alias_path: "/content/{id}" }`

Use returned path in HTML `<img>`, `<script>`, `<link>` tags. Persistent aliases survive restarts. Files are served at `/content/{id}` by the web bundle (the only HTTP endpoint besides agent pages).

## Scene VFX

### `scene_vfx({ js_code, canvas_name? })`
Set canvas 3D VFX (THREE.js). JS receives `scene, THREE, camera, renderer, clock`. Use `this.onFrame = (dt, t) => {...}` for animation. Return a cleanup function. Stored in the canvas agent's `scene_vfx.js`. Emits `scene_vfx_updated` event.

```python
d.scene_vfx({ "js_code": """
const geo = new THREE.TorusKnotGeometry(20, 6, 64, 16)
const mat = new THREE.MeshStandardMaterial({ color: '#ff4488', wireframe: true })
const mesh = new THREE.Mesh(geo, mat)
mesh.position.set(0, 100, 0)
scene.add(mesh)
this.onFrame = (dt, t) => { mesh.rotation.y += 0.01 }
return () => { scene.remove(mesh); geo.dispose(); mat.dispose() }
""" })
```

### `scene_vfx_data({ data, canvas_name? })`
Push live runtime data to the VFX loop. Available in VFX as `window.__vfxData`. Call at 10-30fps to drive reactive visuals. Emits `scene_vfx_data` event.

## Events (subscribe via `t.on(name, handler)`)

- `agent_created` — `{agent: {...}}`
- `agent_moved` — `{agent_id, x, y}`
- `agent_resized` — `{agent_id, width, height}`
- `agent_updated` — `{agent_id, ...changed_fields}`
- `agent_deleted` — `{agent_id}`
- `agent_output` — `{agent_id, html}` (post_output fired)
- `agent_refresh` — `{agent_id}`
- `scene_vfx_updated` / `scene_vfx_data`

## State queries

### `get_state({ scope: '' })` / `get_full_state()`
Full state: all agents with positions, sizes, bundles, sources, outputs. `scope` can filter by display_name.

### `list_agents({ parent: '' })`
Agent list. `parent='canvas_main'` for children of a specific canvas.

## Persistent state layout

```
.fantastic/
  config.json                # Server config (port, PID)
  registry.json              # Server registry
  aliases.json               # Content aliases
  instances.json             # Instance tracking
  agents/
    canvas_{hex}/            # A canvas agent
      agent.json             # {id, bundle: "canvas", ...}
      scene_vfx.js           # VFX code
    terminal_{hex}/          # Per agent (format: {bundle}_{hex6})
      agent.json             # identity, layout, flags
      source.py              # last executed code (log, not source of truth)
      output.html            # ephemeral render
      terminal.log           # scrollback (terminal bundle only)
      chat.json              # chat history (AI / fantastic_agent)
      schedules.json         # per-agent schedules
      memory_long.jsonl      # append-only execution memory
```

## Agent Storage Policy — IMPORTANT

> **Agents are ephemeral runners, not code containers.** All source code lives in the project directory, never inside `.fantastic/`. Ask the user if unsure.

**Rules:**
1. **Code lives in the project** — write .py files to project dirs (`steps/`, `src/`, `notebooks/`).
2. **Agents reference external files** — `d.execute_python({agent_id, code: "exec(open('steps/01.py').read())"})`.
3. **Never pass large code blocks** to `execute_python` — read from project files.
4. **`.fantastic/` is metadata/runtime only**.
5. **`write_file` with `agent_id`** writes a bare filename into that agent's `.fantastic/agents/{id}/` folder — useful for ephemeral agent-owned files.

The pattern: **project owns code, agents own execution and output.**

## File Operations

- `list_files({ path: '' })` — project file tree (excludes `.fantastic/`, `.git/`, `node_modules/`)
- `read_file({ path })` / `write_file({ path, content, agent_id? })`
