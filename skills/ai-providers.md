# AI Providers

Provider lifecycle, hot-swap, concurrency, and multi-instance inference.

## Architecture

```
AIBrain  ──  orchestrator (lock, epoch, conversation integration)
  ├── IntegratedProvider  ──  local HuggingFace models (torch + transformers)
  ├── OllamaProvider      ──  local Ollama server
  ├── AnthropicProvider   ──  Anthropic Messages API (Claude models)
  └── ProxyProvider       ──  forwards to a remote Fantastic instance
```

**AIBrain** owns one active provider at a time. It auto-discovers on first use (config → registered providers in order) and persists the choice to `.fantastic/config.json`.

**Auto-discovery order**: integrated → ollama. Anthropic and proxy require explicit swap.

## Providers

| Name | Requires | Models | Notes |
|------|----------|--------|-------|
| `integrated` | `torch`, `transformers` | HuggingFace (e.g. `Qwen/Qwen3.5-4B`) | Local GPU/CPU, 4-bit quant on CUDA |
| `ollama` | `ollama` package + running server | Any pulled model | Default `localhost:11434` |
| `anthropic` | `anthropic` package + `ANTHROPIC_API_KEY` env | Claude family | API-based, no download |
| `proxy` | Running remote instance | Whatever the remote has | Tunnels through `POST /api/call` |

### Anthropic Setup

```bash
pip install anthropic               # or: pip install fantastic[anthropic]
export ANTHROPIC_API_KEY=sk-...
```

Then swap:
```
ai_swap provider=anthropic
ai_swap provider=anthropic model=claude-opus-4-20250514
```

## Tools

### `ai_status()`
Current provider state: `{configured, provider, model, endpoint, connected}`.

### `ai_providers()`
List registered provider names: `{providers: ["integrated", "ollama", "anthropic", "proxy"]}`.

### `ai_models()`
List models available from the current provider.

### `ai_model(model="")`
Get or set the active model. Without `model=`, returns current. With `model=`, switches and persists.

### `ai_pull(model)`
Download/register a model. Behavior varies by provider:
- **ollama**: downloads from registry
- **integrated**: sets model name (downloads on first use)
- **anthropic**: no-op (sets model name, API models are always available)

### `ai_start()`
Start provider from saved config or auto-discover.

### `ai_stop(force=false)`
Stop current provider, free resources (VRAM, connections).
- `force=false` (default): waits for in-flight generations to finish, then stops.
- `force=true`: interrupts in-flight generations immediately, then stops.

### `ai_swap(provider, model="", instance="", force=false)`
Hot-swap to a different provider. Stops the current one, discovers the target, instantiates, and persists config.
- `provider`: one of `integrated`, `ollama`, `anthropic`, `proxy`
- `model`: optional — picks first available if omitted
- `instance`: required for `proxy` (registered instance ID or name)
- `force=false` (default): waits for in-flight generations to finish before swapping.
- `force=true`: bumps generation epoch immediately, causing all in-flight `ai_generate` calls to return `[provider changing — please wait]` at their next yield.

### `ai_configure()`
Wipe saved config and re-run auto-discover from scratch. Always interrupts in-flight generations.

### `ai_generate(messages)`
Run inference. Takes a list of `{role, content}` message dicts. Returns `{text: "..."}`.
- Used internally by `respond()` and by `ProxyProvider` on remote callers.
- Holds the concurrency lock — only one generation runs at a time per instance.
- If a force-swap or stop happens mid-generation, returns `{error: "provider changing", interrupted: true}`.

## Concurrency Model

All generation and provider lifecycle operations are serialized through an `asyncio.Lock` + generation epoch.

```
┌─────────────────────────────────────────────────────────────┐
│  ai_generate (Agent A)           ai_swap force=true         │
│  ─────────────────────           ─────────────────          │
│  1. check epoch (3)              1. bump epoch → 4          │
│  2. acquire lock                 2. wait for lock           │
│  3. stream tokens...                                        │
│  4. check epoch → mismatch!                                 │
│  5. yield PROVIDER_CHANGING                                 │
│  6. release lock                 3. acquire lock             │
│                                  4. stop old provider        │
│                                  5. start new provider       │
│                                  6. release lock             │
└─────────────────────────────────────────────────────────────┘
```

**Lock**: guards provider state. Only one `generate()` or lifecycle operation (swap/stop/start/configure) runs at a time.

**Epoch** (integer): incremented on every provider change. Generators snapshot the epoch at entry and check it after each `await`. If it changed, they abort with `PROVIDER_CHANGING`.

**`force=false`** (default): swap/stop acquires the lock normally — waits for in-flight generation to finish.

**`force=true`**: bumps epoch *before* acquiring the lock. In-flight generators see the mismatch at their next yield point and bail out, releasing the lock for the swap to proceed.

**`_swapping` flag**: fast-path rejection. New `generate()` calls see it immediately and return `PROVIDER_CHANGING` without waiting for the lock.

## Config Persistence

Saved to `.fantastic/config.json`:

```json
{
  "provider": "anthropic",
  "endpoint": "https://api.anthropic.com",
  "model": "claude-sonnet-4-20250514"
}
```

Proxy configs also include `"instance": "<id>"`. The instance URL is re-resolved on load (tunnel ports may change).

## Multi-Instance / Decoupled Clients

Every Fantastic server exposes the full tool set via `POST /api/call`. To consume multiple instances without proxy:

```python
# Direct HTTP — no brain, no local provider
import httpx

async def generate_on(url, messages):
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{url}/api/call", json={
            "tool": "ai_generate",
            "args": {"messages": messages},
        })
        return r.json()

# Fan-out to N instances
import asyncio
results = await asyncio.gather(
    generate_on("http://host1:8000", msgs),
    generate_on("http://host2:9000", msgs),
)
```

Each instance manages its own lock/epoch — callers don't need to coordinate. If an instance is mid-swap, the caller gets `{error: "provider changing", interrupted: true}` and can retry.
