# Terminal Control

Programmatic control over PTY terminal processes running inside agents.

> **LLM Automation Restriction:** Running LLM CLI agents (e.g. `claude`, `gemini`) in terminals is restricted by subscription. If you are not sure that a running agent or a command you are about to invoke is under an active subscription — ask the user first. Automated agents running on API keys or a Fantastic subscription are allowed.

## Tools

### `terminal_output(agent_id, max_lines=200)`
Read terminal scrollback. Returns last N lines from memory buffer or disk.

### `terminal_restart(agent_id)`
Kill current process and re-fork with the original command/args/env. Same terminal ID so the frontend reconnects seamlessly. Broadcasts `process_closed` + `process_started`.

### `terminal_signal(agent_id, signal=2)`
Send OS signal to the terminal's process. Common signals:
- `2` = SIGINT (Ctrl+C, stop current operation)
- `15` = SIGTERM (graceful shutdown)
- `9` = SIGKILL (force kill)

### `agent_call(target_agent_id, message, from_agent_id)`
Send a message to another agent's terminal. Delivered char-by-char with 20ms delays + Enter.

## REST Endpoints

```
GET  /api/terminal/{id}/output?max_lines=200  → {"output": "...", "lines": N}
POST /api/terminal/{id}/restart               → {"ok": true}
POST /api/terminal/{id}/signal                → {"ok": true}
     Body: {"signal": 2}
POST /api/terminal/{id}/write                 → {"ok": true, "wrote": N}
     Body: {"data": "ls -la\n"}
```

## WebSocket Messages

| Direction | Type | Payload |
|-----------|------|---------|
| frontend→ | `terminal_create` | `{terminal_id, cols, rows, command?, args?}` |
| frontend→ | `terminal_input` | `{terminal_id, data}` |
| frontend→ | `terminal_resize` | `{terminal_id, cols, rows}` |
| frontend→ | `terminal_restart` | `{terminal_id}` |
| frontend→ | `terminal_close` | `{terminal_id}` |
| ←backend | `process_started` | `{agent_id}` |
| ←backend | `terminal_output` | `{terminal_id, data}` |
| ←backend | `process_closed` | `{agent_id}` |

## Scrollback

- 256 KB buffer per terminal (older lines auto-evicted)
- Terminal agents persist scrollback to `.fantastic/agents/{id}/terminal.log`
- Replayed to frontend on browser reload (if terminal dimensions match)

## Example: HTML Knob Controlling a Terminal

> **Note:** HTML agents run in `blob:` iframes — always use absolute URLs.

```js
const API = window.parent.location.origin;

// Stop a running process
await fetch(API + '/api/terminal/' + TID + '/signal', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({signal: 2})
});

// Restart a build server
await fetch(API + '/api/terminal/' + TID + '/restart', {method: 'POST'});

// Send a command
await fetch(API + '/api/terminal/' + TID + '/write', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({data: 'make build\n'})
});

// Read recent output
const res = await fetch(API + '/api/terminal/' + TID + '/output?max_lines=50');
const {output} = await res.json();
```
