# Fantastic Canvas

An infinite canvas where AI agents build anything — a pure orchestrator + bundled agents, connected by a WebSocket-hidden transport.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             FANTASTIC CANVAS                                 │
│                                                                              │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                          CORE (orchestrator only)                     │   │
│  │                                                                       │   │
│  │   engine.py ─ agent_store.py ─ dispatch.py ─ bus.py ─ scheduler.py    │   │
│  │   protocol.py ─ process_runner.py ─ input_loop.py ─ cli.py            │   │
│  │                                                                       │   │
│  │   No HTTP. No UI. Just: agents, dispatch registry, per-agent inbox.   │   │
│  └───────────────────────────┬──────────────────────────────────────────┘   │
│                              │                                               │
│     ┌────────────────────────┼────────────────────────┐                     │
│     │                        │                        │                     │
│     ▼                        ▼                        ▼                     │
│  ┌───────────┐         ┌──────────────┐         ┌──────────────┐             │
│  │ web bundle│         │ AI bundles   │         │ canvas/term/ │             │
│  │ (uvicorn) │         │ (headless)   │         │ fantastic_ag │             │
│  │           │         │              │         │ (has web/)   │             │
│  │ serves UI │◄───────►│  ollama      │         │              │             │
│  │ + WS at   │  bus    │  openai      │         │ canvas agent │             │
│  │ {base}/   │ events  │  anthropic   │         │ terminal     │             │
│  │ {agt}/ws  │         │  integrated  │         │ fantastic_a  │             │
│  │           │         │              │         │              │             │
│  │ injects   │         │ {b}_send     │         │ each has     │             │
│  │ transport │         │ {b}_history  │         │ web/         │             │
│  │ .js       │         │ {b}_save_msg │         │ folder       │             │
│  └─────┬─────┘         └──────────────┘         └──────────────┘             │
│        │                                                                     │
└────────┼─────────────────────────────────────────────────────────────────────┘
         │
         ▼ (HTTP + WS)
   ┌────────────────────────────────────────────────────┐
   │                     BROWSER                         │
   │                                                     │
   │  GET /{agent_id}/             → agent's HTML        │
   │  <script src="_fantastic/transport.js"> ◄─ injected │
   │                                                     │
   │  const t = fantastic_transport()                    │
   │  const d = t.dispatcher                             │
   │  await d.list_agents()       // symmetric w/ core   │
   │  t.on('agent_created', ...)  // events              │
   │  await t.watch('ollama_abc') // mirror inbox        │
   │                                                     │
   │  Zero WS knowledge. Just the injected global.       │
   └────────────────────────────────────────────────────┘
```

**Key principles:**
- **Core has no HTTP.** It's a pure orchestrator (engine + dispatch registry + bus).
- **Web is a bundle.** `bundled_agents/web/` starts a uvicorn per web agent. Multiple web agents = multiple ports/routes. Config (`port`, `base_route`) is hot-reloadable.
- **Every agent is URL-addressed.** `{base}/{agent_id}/` serves that agent's UI. Each gets its own WS channel at `{base}/{agent_id}/ws`.
- **UI agents never see WebSocket.** The web bundle injects `fantastic_transport()` as a global. UI uses `dispatch/dispatcher/on/emit/watch`. That's it.
- **Dispatch is symmetric.** `t.dispatcher.list_agents({parent: 'canvas_main'})` on frontend ≡ `_DISPATCH["list_agents"](parent="canvas_main")` on backend. Same names, same args.
- **AI bundles are headless.** They register dispatch handlers (`ollama_send`, etc.) and emit events to the bus. No UI of their own.
- **`fantastic_agent` is the universal chat UI.** Configure with `upstream_agent_id` + `upstream_bundle` to front any AI backend via `transport.watch(upstream_id)`.

The conversation buffer (`{who}:{message}`) is the CLI log. Color-coded: core=magenta, user=green, agent/bundle=cyan.

## Quick Start

```bash
# Development (uv)
uv sync                                                      # install deps + create venv
uv run fantastic add web                                     # add web bundle (first run auto-adds)
uv run fantastic add canvas                                  # add canvas bundle
uv run fantastic add terminal                                # add terminal bundle
uv run fantastic                                             # starts engine + all web agents

# Frontend build (once after clone / after transport.ts changes)
cd bundled_agents/canvas/web
npm install
npm run build                                                # canvas UI + transport.js
npm run build:transport                                      # transport.ts → dist/transport.js only

# Tests
uv run pytest core/tests/ bundled_agents/ -v -x              # backend
cd bundled_agents/canvas/web && npx vitest run               # frontend

# CLI subcommands
fantastic list                                               # show bundles + agents
fantastic add <bundle>                                       # add a bundle (e.g. ollama, fantastic_agent)
fantastic remove <bundle>                                    # remove a bundle
fantastic serve                                              # headless server (no input loop)

# Interactive mode
fantastic                                                    # starts input loop + web
> list
> add canvas
> log

# AI providers are now bundled agents (not a central brain anymore)
> add ollama                                                 # create an ollama backend agent
> add fantastic_agent                                        # create a chat UI proxy
# Then configure fantastic_agent via tool call:
#   fantastic_agent_configure(agent_id=<fa_id>, upstream_agent_id=<ollama_id>, upstream_bundle="ollama")

# Multiple web agents (ports, base routes)
> add web                                                    # additional web agent, default port 8888
# Then: web_configure(agent_id=<web_id>, port=9000, base_route="/admin")

# Install globally via uv
uv tool install ./core
uv tool install ./core[torch]

# Docker
docker-compose up
```

## Skills

Skills are provided by bundles via their own handbook tools.

| Tool | What It Covers |
|------|----------------|
| `get_handbook` | Returns CLAUDE.md (this file) |
| `get_handbook_canvas` | Agent CRUD, layout, content aliases, VFX |
| `get_handbook_terminal` | Read output, restart processes, send signals, scrollback |

Each AI bundle (`ollama`, `openai`, `anthropic`, `integrated`) has its own `skills/{bundle}.md`. The `web` bundle has `skills/web.md` documenting port/base_route config. `fantastic_agent` has `skills/fantastic_agent.md` for upstream configuration.

## Dispatch (the ONE vocabulary)

`_DISPATCH` / `_TOOL_DISPATCH` hold every tool. Names mirror 1:1 on the frontend via `fantastic_transport().dispatcher`.

**Core**: `create_agent`, `list_agents`, `read_agent`, `delete_agent`, `update_agent`, `rename_agent`, `refresh_agent`, `post_output`, `get_state`, `get_full_state`, `execute_python`, `agent_run`, `agent_call`, `get_handbook`, `register_template`, `list_templates`, `server_logs`, `read_agent_memory`, `append_agent_memory`, `conversation_log`, `conversation_say`, `core_chat_message`
**Scheduler** (`scheduler` bundle): `agent_call verb=schedule|unschedule|list|pause|resume|tick_now|history`. Every fire emits a `schedule_fired` event on the scheduler's inbox AND the target's inbox, and appends to a history sidecar. Internal handler names: `scheduler_schedule`, `scheduler_unschedule`, `scheduler_list`, `scheduler_pause`, `scheduler_resume`, `scheduler_tick_now`, `scheduler_history`.
**Canvas**: `move_agent`, `resize_agent`, `scene_vfx`, `scene_vfx_data`, `spatial_discovery`, `get_handbook_canvas`
**Terminal**: `terminal_output`, `terminal_restart`, `terminal_signal`, `get_handbook_terminal`
**Process**: `process_create`, `process_input`, `process_resize`, `process_enter`, `process_close`, `process_attach`, `process_output`, `process_restart`, `process_signal`
**Web**: `web_configure`
**AI bundles** (per `{bundle}` in ollama/openai/anthropic/integrated): `{bundle}_send`, `{bundle}_interrupt`, `{bundle}_save_message`, `{bundle}_history`, `{bundle}_configure`
**fantastic_agent**: `fantastic_agent_get_config`, `fantastic_agent_configure`, `fantastic_agent_save_message`, `fantastic_agent_history`

## Protocol (frontend ↔ backend)

**No REST.** Pure WebSocket, one channel per agent at `ws://{host}/{base}/{agent_id}/ws`. Everything flows over the injected `fantastic_transport()` global.

Message shapes (JSON, see `core/protocol.py`):
```
C→S  {"type":"call",  "tool":"<name>", "args":{...}, "id":"<uuid>"}
C→S  {"type":"emit",  "event":"<name>", "data":{...}}
S→C  {"type":"reply", "id":"<uuid>", "data":{...}}
S→C  {"type":"error", "id":"<uuid>", "error":"<msg>"}
S→C  {"type":"event", "event":"<name>", "data":{...}}
```

Frontend API (from the injected global):
```ts
const t = fantastic_transport()
const d = t.dispatcher
await d.list_agents({parent: 'canvas_main'})   // dispatch (symmetric with backend)
t.on('agent_created', handler)                  // subscribe to events
t.onAny((event, data) => ...)                   // wildcard
await t.watch('ollama_abc')                     // mirror another agent's inbox
```

**Web|dispatch is THIN**: pure lookup in `_DISPATCH` and invoke. No translation, no aliasing. Auth/ACL/rate-limiting are future layers `# later` on top.

Events are published to per-agent bus inboxes (see `core/bus.py`). The web bundle's WS handler drains inboxes into WS frames for connected clients.

## Best Practices

- **Never inline base64 in `post_output`** — payloads over 512KB crash the canvas. Use `agent_call(web_id, verb="alias", kind="file", path=...)` → serve at `/content/{alias_id}`.
- **Large assets** (images, plots, data): save to project dir → `agent_call` alias verb on the web agent → URL in HTML.
- **Never spawn cascades of `fantastic_agent`** — they are user-facing chat UIs, not API-callable agents. Ask the user first if unsure.
- **UI agents never touch WebSocket.** Only `fantastic_transport()`. No `new WebSocket(...)`, no `fetch('/api/...')`.
- **Agent IDs are `{bundle}_{hex6}`** (e.g. `terminal_a3f2b1`, `ollama_b04b35`). Bundle is required when creating an agent.

## Architecture notes

- **Core has no HTTP.** `core/` is Engine + AgentStore + Dispatch + Bus. Transport is a bundle (`web`). Scheduling is a bundle (`scheduler`). Filesystem is a bundle (`file`). Connected peers are a bundle (`instance`).
- **Web agents are hot-reloadable.** `web_configure(agent_id, port=..., base_route=...)` cancels+restarts uvicorn with new config. Clients auto-reconnect (transport.ts handles it).
- **Multiple web agents can coexist.** Different ports, different base routes, different policies (future: `readonly` for broadcast viewers).
- **Each agent has a URL and a WS channel.** `{base}/{agent_id}/` serves HTML, `{base}/{agent_id}/ws` is the protocol channel. The web bundle injects `<script src="/_fantastic/transport.js">` into every served HTML page.
- **`delete_lock`**: boolean on `agent.json`; `delete_agent` refuses deletion when true.
- **Agent memory**: append-only JSONL at `.fantastic/agents/{id}/memory_long.jsonl`.
- **Code execution**: Python subprocess (stateless, one-shot) via `execute_python` dispatch.
- **Filesystem access (`file` bundle)**: `add file name=<display> root=<abs> [readonly=true]` creates one `file_<hex6>` agent per root. Verbs reached via `agent_call verb=list|read|write|delete|rename|mkdir`. Core has no filesystem code. Quickstart seeds `file_project` (root = project_dir). See `bundled_agents/file/skills/file.md`.
- **Connected instances**: `add instance` creates one `instance_<hex6>` agent per connected fantastic (transport `ws` or `ssh`). Verbs reached via `agent_call verb=start|stop|status|call`. No core-level subprocess tracking — all state (url, tunnel_pid, local_port) lives in the instance agent's `agent.json`. See `bundled_agents/instance/skills/instance.md`.
- **Scheduler (`scheduler` bundle)**: one tick loop per `scheduler_<hex6>` agent. Schedules stored in `.fantastic/agents/{sched_id}/schedules.json`; every fire appended to `history.jsonl` + emitted as `schedule_fired` event on the bus (on both scheduler's and target's inbox). Verbs via `agent_call`: `schedule`, `unschedule`, `list`, `pause`, `resume`, `tick_now`, `history`. Quickstart seeds `scheduler_main`. See `bundled_agents/scheduler/skills/scheduler.md`.

## Project Structure

```
fantastic_canvas/
├── CLAUDE.md, fantastic.md, .env, .python-version
├── core/                                   # PURE ORCHESTRATOR — no HTTP, no UI
│   ├── cli.py                              # Entrypoint: boots engine + web bundle serve tasks
│   ├── engine.py                           # Agent store + code runner orchestration
│   ├── agent_store.py                      # Persistent .fantastic/ agent dirs
│   ├── dispatch.py                         # _DISPATCH, _TOOL_DISPATCH, ToolResult
│   ├── bus.py                              # Per-agent inbox + global firehose + watch()
│   ├── protocol.py                         # Wire protocol reference (constants + docstring)
│   ├── process_runner.py                   # PTY terminal management
│   ├── scheduler.py                        # Per-agent persistent schedules
│   ├── conversation.py                     # Ring buffer + color formatting
│   ├── input_loop.py                       # CLI loop (no AI, no HTTP)
│   ├── code_runner.py                      # Subprocess Python executor
│   ├── instance_backend.py                 # SSH/local instance launcher
│   └── tools/                              # Dispatch handlers grouped by concern
│       ├── _agents.py, _bundles.py, _content.py, _conversation.py
│       ├── _process.py, _registry.py, _instances.py, _schedules.py
│       └── _instance_tracking.py, _server_log.py
├── bundled_agents/                         # All transports + agents live here
│   ├── _web_shared/                        # Shared JS transport (served by web bundle)
│   │   ├── transport.ts                    # Source of truth
│   │   ├── dist/transport.js               # Built (gitignored, made by esbuild)
│   │   └── README.md
│   ├── _ai_shared/                         # Shared Python helpers for AI bundles
│   │   ├── ai_dispatch.py                  # AiBundleRuntime (factory)
│   │   ├── agentic_loop.py, messages.py
│   │   ├── provider_pool.py, provider_protocol.py
│   │   ├── chat_storage.py, tool_schema.py
│   ├── web/                                # Transport bundle (HTTP + WS)
│   │   ├── template.json, tools.py         # serve(), web_configure, hot-reload
│   │   ├── app.py                          # FastAPI factory (per web agent)
│   │   └── skills/web.md
│   ├── canvas/                             # Canvas UI (layout host)
│   │   ├── template.json, tools.py         # move_agent, resize_agent, VFX, spatial
│   │   ├── default_vfx.js
│   │   └── web/                            # React + Vite
│   │       ├── package.json                # build:transport → _web_shared/dist
│   │       ├── vite.config.ts, tsconfig.json
│   │       └── src/
│   │           ├── main.tsx, App.tsx, types.ts, styles.css
│   │           ├── hooks/useTransport.ts   # Thin wrap around fantastic_transport()
│   │           ├── components/             # Canvas, AgentShape, base/, WebGLLayer
│   │           └── plugins/                # registry + types (layout plugins only)
│   ├── terminal/                           # Terminal agent (PTY + xterm)
│   │   ├── template.json, tools.py
│   │   ├── plugin.ts                       # Canvas layout plugin (iframe only)
│   │   ├── source.py
│   │   ├── web/index.html                  # xterm page using fantastic_transport()
│   │   └── skills/terminal-control.md
│   ├── fantastic_agent/                    # Generic chat UI (fronts any AI)
│   │   ├── template.json, tools.py         # configure, history, save_message
│   │   ├── plugin.ts                       # Canvas layout plugin (iframe only)
│   │   ├── web/index.html                  # Chat UI using transport.watch(upstream)
│   │   └── skills/fantastic_agent.md
│   ├── ollama/, openai/, anthropic/, integrated/   # Headless AI backends
│   │   ├── template.json, tools.py         # {bundle}_send, _history, _save_message, ...
│   │   ├── provider.py                     # Model/API client
│   │   └── skills/{bundle}.md
│   └── quickstart/                         # Setup wizard
├── .fantastic/                             # Persistent runtime state
│   ├── config.json, registry.json, aliases.json, instances.json
│   └── agents/{bundle}_{hex6}/
│       ├── agent.json                      # {id, bundle, display_name, x, y, ...}
│       ├── source.py, output.html
│       ├── chat.json                       # Chat history (fantastic_agent / AI bundles)
│       ├── schedules.json                  # Per-agent scheduler entries
│       └── memory_long.jsonl               # Append-only execution memory
├── scripts/                                # Build & test scripts
└── docs/                                   # Architecture & analysis docs
```

## Environment

- **uv**: project manager + virtualenv (`uv sync` to set up)
- **Python**: 3.11+ (pinned in `.python-version`)
- **Backend**: FastAPI, uvicorn, httpx
- **Frontend**: React 18, Vite 6, TypeScript
- **Ports**: Backend (auto), Frontend dev 3000
- **Docker**: python:3.11-slim + Node.js 20

## LLM Automation Restriction

Running LLM CLI agents (e.g. `claude`, `gemini`) in terminals is **restricted by subscription**. If you are not sure that a running agent or a command you are about to invoke is under an active subscription — **ask the user first**. Automated agents running on API keys or a Fantastic subscription are allowed. Do not spawn or automate LLM CLI agents without confirming authorization.

## Agent Storage Policy

**Agents are ephemeral runners, not code containers.** All source code MUST live in the project directory (version controlled), never inside `.fantastic/`.

- **DO**: store .py files in the project (e.g. `steps/01_load.py`, `src/train.py`)
- **DO**: use `execute_python("exec(open('steps/01_load.py').read())", agent_id)` to run external files
- **DO NOT**: pass large code blocks directly to `execute_python` — read from project files instead
- **DO NOT**: treat `source.py` in `.fantastic/agents/{id}/` as a code store — it's an auto-generated log, not source of truth
- `.fantastic/` should contain only: `agent.json` (metadata), `output.html` (ephemeral render), and lightweight config

The pattern is: **project owns code, agents own execution and output.** If you are unsure where something should be stored — **ask the user before proceeding**.

## File Paths — Always Relative

Terminals start with `cwd` set to the project directory. **Always use relative paths** — never `~/...` or absolute paths.

- **DO**: `open("notebooks/config.yaml")`, `os.path.join("keys", "creds.json")`
- **DO NOT**: `os.path.expanduser("~/Projects/my-project/notebooks/config.yaml")`
- **Why**: Absolute paths break in Docker (`-v $(pwd):/workspace`) where `~` = `/workspace`, not your home dir. Relative paths work everywhere — local, pip-installed, and containerized.

## Pre-push Checks

Run these before pushing to ensure CI passes:

```bash
uvx ruff check core/ bundled_agents/                         # Python lint (all)
uvx ruff format --check core/ bundled_agents/                # Python format
cd bundled_agents/canvas/web && npm ci && npx tsc --noEmit   # TypeScript type check
cd bundled_agents/canvas/web && npm run build:transport      # Rebuild transport.js if .ts changed
uv sync --dev && uv run pytest core/tests/ bundled_agents/ -v -x  # Backend tests
```

## Conventions

- Agent IDs: `{bundle}_{hex6}` format (e.g. `terminal_a3f2b1`, `ollama_b04b35`). Bundle is mandatory when creating agents.
- Every bundle's `tools.py` exposes a `NAME = "..."` constant at module level.
- All async (`asyncio` throughout).
- Tests: `pytest-asyncio` with `asyncio_mode = "auto"`.
- `.fantastic/` excluded from file listings.
- UI code only uses `fantastic_transport()` — never `fetch`, `new WebSocket`, or `/api/...` URLs.
