# Fantastic

[![Tests](https://github.com/Alexadar/fantastic_canvas/actions/workflows/test-on-label.yml/badge.svg)](https://github.com/Alexadar/fantastic_canvas/actions/workflows/test-on-label.yml)
[![Lint & Type Check](https://github.com/Alexadar/fantastic_canvas/actions/workflows/lint-typecheck.yml/badge.svg)](https://github.com/Alexadar/fantastic_canvas/actions/workflows/lint-typecheck.yml)
[![CodeQL](https://github.com/Alexadar/fantastic_canvas/actions/workflows/codeql.yml/badge.svg)](https://github.com/Alexadar/fantastic_canvas/actions/workflows/codeql.yml)

A post-IDE editor — an infinite canvas where AI agents build anything.

## How it looks

![Fantastic Canvas](imgs/scr1.png)

A Fantastic environment created by Claude to help learn Conditional Flow Matching. I asked the coding agent to learn from `.fantastic`, read the handbook, find/clone and understand the CFM repo, and create explanation, training, and visualisation UI. A very fun and quick way to do self-presentations and learning sessions.

## Architecture

```
┌────────────────────────┐
│   CORE (orchestrator)  │   Engine + AgentStore + Dispatch + Bus + Scheduler
│   No HTTP. No UI.      │   Pure Python, async throughout.
└──────────┬─────────────┘
           │  dispatch / bus events
           ▼
┌────────────────────────────────────────────────┐
│                BUNDLED AGENTS                   │
│                                                 │
│  web/     — HTTP + WS transport (uvicorn)       │
│             injects fantastic_transport() JS    │
│                                                 │
│  canvas/  — layout + iframe host  (has web/)    │
│  terminal/— PTY + xterm page      (has web/)    │
│  fantastic_agent/ — chat UI proxy (has web/)    │
│                                                 │
│  ollama/ openai/ anthropic/ integrated/         │
│           — headless AI backends                │
│                                                 │
│  html/ dashboard/ quickstart/                   │
└────────────────────┬───────────────────────────┘
                     │
                     ▼  ws://host/{agent_id}/ws
               ┌──────────────┐
               │   Browser    │  fantastic_transport() global
               │              │  → dispatch / on / watch / ...
               └──────────────┘
```

UI code never sees WebSocket — it uses the injected `fantastic_transport()` global. Same dispatch names on frontend and backend. See `CLAUDE.md` for the full protocol.

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Node.js 18+ (for frontend build)

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
# Or via Homebrew
brew install uv
```

## Installation

```bash
# From source (development)
uv sync                                  # Python 3.11+ deps + venv
cd bundled_agents/canvas/web
npm install && npm run build             # builds canvas UI + _web_shared/dist/transport.js

# Install globally
uv tool install ./core
uv tool install ./core[torch]            # with PyTorch (CPU/CUDA/MPS auto)
```

## Usage

```bash
fantastic                                # engine + auto-creates default web agent on :8888
# Open http://localhost:8888/{canvas_agent_id}/ in browser
```

### Adding agents

```bash
> add canvas                             # spatial canvas host
> add terminal                           # PTY terminal
> add ollama                             # headless Ollama backend
> add fantastic_agent                    # chat UI proxy — configure upstream_agent_id
```

AI providers are now bundled agents. Create a backend (e.g. `ollama`), then a `fantastic_agent` UI to chat with it. Configure via dispatch:

```
fantastic_agent_configure(agent_id=<fa_id>, upstream_agent_id=<ollama_id>, upstream_bundle="ollama")
```

### Multiple web agents

```bash
> add web                                # another web agent
# Then: web_configure(agent_id=<web_id>, port=9000, base_route="/admin")
```

Each web agent has its own uvicorn, its own config, its own base route. Hot-reloads on config change.

## Testing

```bash
uv run pytest core/tests/ bundled_agents/ -v -x   # backend
cd bundled_agents/canvas/web && npx vitest run   # frontend
```

## Security

Intended for personal use. Do not expose to the web — it can compromise your machine.

## License

Apache 2.0 — see [LICENSE](LICENSE).
