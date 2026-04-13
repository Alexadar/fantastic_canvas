# Ollama Agent

Runs local LLMs via an Ollama server (default `http://localhost:11434`).

## Configuration (stored in agent.json)

- `endpoint`: Ollama server URL (default: `http://localhost:11434`)
- `model`: Model name (e.g. `qwen3:8b`, `gemma4:e2b`). First `ollama list` entry if empty.
- `context_length`: Context window — auto-detected from model info

Reconfigure via `ollama_configure` tool call. Generally unnecessary — each bundle auto-configures on first use.

## Dispatch API

This bundle registers these WS dispatch handlers (use as message `type`):

| Dispatch | Args | Purpose |
|---|---|---|
| `ollama_send` | `agent_id, text` | Process a user message. Streams `ollama_response` chunks. |
| `ollama_interrupt` | `agent_id` | Stop current generation. |
| `ollama_save_message` | `agent_id, role, text, mode?` | Persist a message to chat.json. |
| `ollama_history` | `agent_id` | Load chat.json → reply `ollama_history_response`. |
| `ollama_configure` | `agent_id, endpoint?, model?` | Update agent config. |

## Broadcasts

- `ollama_response` — `{agent_id, text, done}` streaming chunks
- `ollama_state` — `{agent_id, state}` (thinking/responding/idle)
- `ollama_error` — `{agent_id, error}`
- `ollama_history_response` — reply to `ollama_history`

## Notes

- Persistence is UI-triggered: backend never auto-saves. UI calls `ollama_save_message` before/after sending.
- Multiple `ollama` agents can coexist — each has its own config + chat.json.
