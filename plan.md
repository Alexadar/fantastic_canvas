# Plan: Interactive AI Brain Discovery & Control API

## Problem

The canvas frontend has no awareness of AI brain state. If a user opens the canvas and no provider is configured, there's no interactive way to discover that, see options, and activate one. The AI lifecycle tools exist but aren't wired into the real-time WS broadcast system or exposed as a coherent plugin surface.

## Design Principles

- Follow the **instance management pattern**: tools → ToolResult with broadcast → WS clients react
- AI status changes broadcast `ai_changed` to all WS clients (like `instances_changed`)
- Frontend hook can subscribe and render interactive UI
- No new REST endpoints — everything goes through existing `POST /api/call` and WS dispatch

---

## Step 1: Backend — Broadcast `ai_changed` on every AI lifecycle event

**File: `core/tools/_ai.py`**

Add an `_ai_state()` helper that returns the current AI snapshot (provider, model, status, available providers). Every mutating AI tool (`ai_start`, `ai_stop`, `ai_swap`, `ai_configure`, `ai_model`) appends a broadcast:

```python
async def _ai_state() -> dict:
    brain = _engine.ai
    provider = brain.provider
    config = load_config(brain._project_dir) or {}
    return {
        "provider": config.get("provider"),
        "model": config.get("model"),
        "connected": provider is not None,
        "swapping": brain.swapping,
        "providers": AIBrain.available_providers(),
    }
```

Tools that mutate state return:
```python
return ToolResult(
    data=...,
    broadcast=[{"type": "ai_changed", **await _ai_state()}],
)
```

**Tools to update:** `ai_stop`, `ai_start`, `ai_swap`, `ai_configure`, `ai_model`.

`ai_status` stays read-only (no broadcast). `ai_generate` stays broadcast-free (it's a hot path).

## Step 2: Backend — Add `ai_discover` tool

**File: `core/tools/_ai.py`**

New tool that probes all registered providers without activating any. Returns what's available so the frontend can show options before the user commits.

```python
@register_dispatch("ai_discover")
async def _ai_discover(**kwargs) -> ToolResult:
    """Probe all providers, return availability + models."""
    from ..ai.brain import _PROVIDERS
    results = []
    for cls, endpoint in _PROVIDERS:
        r = await cls.discover(endpoint)
        results.append({
            "provider": r.provider_name,
            "available": r.available,
            "models": r.models,
            "endpoint": r.endpoint,
            "error": r.error,
        })
    return ToolResult(data={"providers": results})
```

This gives the frontend everything it needs to render a provider/model picker without committing to anything.

## Step 3: Frontend — `useAI` hook

**File: `bundled_agents/canvas/web/src/hooks/useAI.ts`**

React hook that:
1. On mount, calls `request('ai_status')` to get initial state
2. Subscribes to WS `ai_changed` messages for real-time updates
3. Exposes: `{ status, discover, swap, stop, start }`

```typescript
interface AIStatus {
  provider: string | null
  model: string | null
  connected: boolean
  swapping: boolean
  providers: string[]
}

export function useAI(
  request: (tool: string, args?: Record<string, unknown>) => Promise<unknown>,
  subscribe: (fn: (msg: WSMessage) => void) => () => void,
) {
  const [status, setStatus] = useState<AIStatus | null>(null)

  useEffect(() => {
    request('ai_status').then((data) => setStatus(data as AIStatus))
    return subscribe((msg) => {
      if (msg.type === 'ai_changed') {
        const { type, ...rest } = msg
        setStatus(rest as AIStatus)
      }
    })
  }, [])

  const discover = () => request('ai_discover') as Promise<{ providers: DiscoverEntry[] }>
  const swap = (provider: string, opts?: { model?: string; instance?: string }) =>
    request('ai_swap', { provider, ...opts })
  const stop = () => request('ai_stop')
  const start = () => request('ai_start')

  return { status, discover, swap, stop, start }
}
```

## Step 4: Frontend — AI status indicator in Canvas

**File: `bundled_agents/canvas/web/src/components/AIStatus.tsx`**

Minimal floating UI element (bottom-right corner) that:

1. **Connected state**: Shows provider name + model as a small chip (e.g. `ollama · llama3.2`). Click to expand menu with stop/switch options.
2. **No provider**: Shows "No AI" chip. Click opens a dropdown:
   - Calls `discover()` to probe available providers + models
   - Renders options as a selectable list
   - On select, calls `swap(provider, { model })`
   - Shows loading state during swap (`swapping: true` from `ai_changed`)
3. **Swapping state**: Shows spinner + "Switching..."

Standalone React component integrated into `Canvas.tsx` as a sibling overlay.

**File: `bundled_agents/canvas/web/src/components/Canvas.tsx`**

Mount `<AIStatus />` inside the canvas container, passing `request` and `subscribe` from the existing WS hook.

## Step 5: Handbook & CLAUDE.md updates

**File: `skills/ai-management.md`** (new skill doc)

Document the full AI infrastructure:
- Tools: `ai_status`, `ai_discover`, `ai_models`, `ai_model`, `ai_swap`, `ai_start`, `ai_stop`, `ai_configure`, `ai_providers`, `ai_generate`, `ai_pull`
- WS broadcast: `ai_changed` event shape and when it fires
- Provider types: integrated (HuggingFace local), ollama (local server), proxy (remote instance)
- Proxy setup flow: register/launch instance → `ai_swap provider=proxy instance=<id>`

**File: `CLAUDE.md`**

- Add `ai_discover`, `ai_generate` to the **Core** tools list
- Add to Skills table: `get_handbook` skill `ai-management`
- Add `ai_changed` to WS incoming (backend → frontend) protocol section

---

## File Summary

| File | Change |
|------|--------|
| `core/tools/_ai.py` | Add `_ai_state()`, `ai_discover` tool, broadcast `ai_changed` from mutating tools |
| `bundled_agents/canvas/web/src/hooks/useAI.ts` | New: AI status hook |
| `bundled_agents/canvas/web/src/components/AIStatus.tsx` | New: floating AI indicator + provider picker |
| `bundled_agents/canvas/web/src/components/Canvas.tsx` | Mount `<AIStatus />` |
| `skills/ai-management.md` | New skill doc |
| `CLAUDE.md` | Update tools, skills, WS protocol |

## Out of Scope

- Chat UI in canvas (separate feature — uses `brain.respond()`)
- Streaming tokens over WS (current `ai_generate` is request/response)
- AI as a canvas agent type (would be a plugin like terminal)
