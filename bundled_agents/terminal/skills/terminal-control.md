# Terminal Control

Programmatic control over PTY terminal processes running inside agents.

> **LLM Automation Restriction:** Running LLM CLI agents (e.g. `claude`, `gemini`) in terminals is restricted by subscription. If you are not sure that a running agent or a command you are about to invoke is under an active subscription — ask the user first. Automated agents running on API keys or a Fantastic subscription are allowed.

## Dispatch names

All callable from any frontend via `t.dispatcher.{name}(args)` or directly on the backend as `_DISPATCH[name](**args)`.

### `terminal_output(agent_id, max_lines=200)`
Read terminal scrollback. Returns `{"output": "...", "lines": N}`.

### `terminal_restart(agent_id)`
Kill current process and re-fork with the original command/args/env. Same agent ID so the frontend reconnects seamlessly. Emits `process_closed` + `process_started` events.

### `terminal_signal(agent_id, signal=2)`
Send OS signal to the terminal's process. Common signals:
- `2` = SIGINT (Ctrl+C, stop current operation)
- `15` = SIGTERM (graceful shutdown)
- `9` = SIGKILL (force kill)

### `process_input(agent_id, data)`
Write bytes to the PTY stdin. The terminal page uses this for xterm input.

### `process_resize(agent_id, cols, rows)`
Resize the PTY.

### `process_create(agent_id, cols, rows, command?, args?, env_extra?)`
Create or reconnect a PTY for an agent.

### `agent_call(target_agent_id, message, from_agent_id?)`
Send a message to another agent. For terminals: typed char-by-char (20ms between) + Enter. For AI bundles: routed to `{bundle}_send`.

## Events (subscribe via `t.on(name, handler)`)

| Event | Payload | When |
|---|---|---|
| `process_output` | `{agent_id, data}` | PTY stdout chunk |
| `process_started` | `{agent_id, pid}` | PTY spawned |
| `process_closed` | `{agent_id, code}` | PTY exited |

## Scrollback

- 256 KB buffer per terminal (older lines auto-evicted)
- Persisted to `.fantastic/agents/{id}/terminal.log`
- Replayed on page reload (resize pty BEFORE replay so TUIs redraw correctly)

## Example: HTML page controlling a terminal

The terminal page is served at `{base}/{terminal_agent_id}/` with `fantastic_transport()` pre-injected. Same primitives work for any agent HTML that wants to drive a terminal:

```html
<script>
  const t = fantastic_transport()
  const d = t.dispatcher
  const TID = 'terminal_a3f2b1'  // or scan list_agents() for bundle=="terminal"

  // Watch the target terminal's events (mirror into my inbox)
  await t.watch(TID)
  t.on('process_output', e => {
    if (e.agent_id === TID) console.log(e.data)
  })

  // Send Ctrl+C
  await d.terminal_signal({ agent_id: TID, signal: 2 })

  // Restart
  await d.terminal_restart({ agent_id: TID })

  // Send a command (types + Enter)
  await d.process_input({ agent_id: TID, data: 'ls -la\n' })

  // Read recent output
  const res = await d.terminal_output({ agent_id: TID, max_lines: 50 })
  console.log(res.output)
</script>
```

No REST, no fetch — just the transport.
