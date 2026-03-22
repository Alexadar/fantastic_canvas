# Plan: AI Integration (Ollama-only, @-handles)

## Concept

Fantastic becomes an AI coding assistant in the terminal (like OpenCoder/Aider).
User types freely — unrecognized input goes to AI instead of becoming dead conversation.
Canvas agents run in parallel and can interact with the main conversation via `@` handles.

## @ Handle Routing (existing system extended)

```
"fix the bug"              → AI responds (default for non-commands)
"@ai explain this"         → AI explicitly
"@canvas hello"            → message to canvas agent
"@terminal_a3f2b1 ls"      → message to specific agent
"add canvas"               → existing core command (unchanged)
"ai status"                → AI management command (new)
```

Key change: **fallback for unrecognized input changes from `conversation.say("user", text)` to AI chat**.

## New Files

### `core/ai/__init__.py`
Package init, re-exports AIBrain + OllamaProvider.

### `core/ai/provider.py` — OllamaProvider
Thin wrapper around `ollama.AsyncClient`:
- `check()` → bool (health check)
- `chat(messages)` → AsyncIterator[str] (streaming)
- `list_models()` → list[str]
- `pull(model)` → AsyncIterator[str] (progress)
- `model` property + `set_model()`

### `core/ai/brain.py` — AIBrain
Reads conversation buffer, builds messages, streams from provider:
- `respond(user_message)` → AsyncIterator[str]
- `_build_messages()` → conversation buffer → ollama chat format
- `available` property (is provider reachable?)
- Maps: who="user" → role=user, who="ai" → role=assistant, others → role=system

### `core/ai/config.py` — Config
Load/save `.fantastic/ai.json`:
```json
{"model": "qwen2.5-coder:7b", "endpoint": "http://localhost:11434"}
```

### `core/tools/_ai.py` — AI dispatch tools
Registered via `@register_dispatch` / `@register_tool`:
- `ai_status` → availability, model, endpoint
- `ai_models` → list local models
- `ai_model` → switch model
- `ai_pull` → pull model

## Modified Files

### `core/pyproject.toml`
Add `"ollama>=0.4"` to default dependencies.

### `core/conversation.py`
Add `AI_COLOR = "\033[33m"` (yellow) and `"ai"` to color routing.

### `core/engine.py`
- Create OllamaProvider + AIBrain in `__init__` (from config)
- Expose `self.ai` property → AIBrain
- In `start()`: non-fatal provider health check

### `core/input_loop.py`
The critical change — two parts:

1. **Fallback**: when text is not a command and not `@`-routed, send to AI:
```python
# old: conversation.say("user", text)
# new:
conversation.say("user", text)
if self._engine and self._engine.ai.available:
    # stream AI response to terminal
else:
    # silent fallback (no AI configured)
```

2. **Streaming output**: print chunks with AI_COLOR as they arrive, save full response to buffer when done.

3. **Engine reference**: InputLoop needs access to engine (currently it doesn't have it). Pass via constructor or setter after lifespan creates it.

### `core/recipients.py`
Add `ai` subcommands to CoreRecipient.parse():
- `ai status` → `("ai_status", {})`
- `ai models` → `("ai_models", {})`
- `ai model <name>` → `("ai_model", {"model": name})`
- `ai pull <name>` → `("ai_pull", {"model": name})`

### `core/server/_lifespan.py`
After `engine.start()`: log AI availability (non-fatal).

### `core/tools/__init__.py`
Add `from . import _ai` to import block.

## Streaming UX

```
> what does this function do?
ai         : The `resolve_working_dir` method walks up the parent chain...
             it returns the root parent's working_dir or falls back to
             project_dir. This ensures child agents inherit their...
```

Yellow-colored, streamed chunk-by-chunk, padded name column like all other actors.

## Canvas Agent Conversation Participation

Already works via existing tools:
- Canvas agents write to buffer via `conversation_say` tool
- Canvas agents read buffer via `conversation_log` tool
- AI sees everything in the buffer (it reads the full history)
- Future AI-backed canvas agent: same pattern — subscribe to buffer, route through own AI provider

## Error States

| State | Behavior |
|---|---|
| Ollama not installed/running | `ai status` → "unavailable", typing falls through to plain `conversation.say()` |
| Model not pulled | Error message + suggest `ai pull <model>` |
| Connection lost mid-stream | Partial response saved, error shown |
