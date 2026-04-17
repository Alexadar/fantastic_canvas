# `instance` bundle self-test

Scope: one bundle. Every verb goes through `agent_call`.

## Before you start — ASK THE USER

The WS path is trivially testable against `localhost` (spin a second
fantastic on another port). The SSH path spawns a real subprocess over
your SSH config, creates a tunnel to a remote host, and launches a
remote `fantastic serve`.

> Do you want to exercise the **SSH path** too?
>
> - **No** → skip S1–S4; run only the WS tests (W1–W6).
> - **Yes** → which SSH alias (from `~/.ssh/config`) should I use, and
>   what's the project directory on the remote? E.g.
>   `ssh_host=gpu-box remote_dir=/home/me/fantastic_canvas`.
>   The remote needs `fantastic` on PATH (or set `remote_cmd=...`).
>   I'll spawn the tunnel + remote server, call `list_agents` over it,
>   then stop it. Nothing persists on the remote.

Record the user's choice in the final report. Do not invent an SSH host.

## Pre-flight (WS path — always)

Start a second fantastic on port 8889:
```bash
cd /tmp && rm -rf .fantastic && uv run --project /path/to/repo fantastic &
# (the second process serves its own empty state on 8889 via `add web`)
```
Alternative: run `pytest bundled_agents/instance/tests/` — the mocked
bundle tests exercise every branch without a second process.

## WS tests

Drive from the primary fantastic's CLI / WS.

### W1 — `add instance` (ws) creates agent
```
add instance name=local_peer transport=ws url=ws://localhost:8889
```
Expected: `instance 'local_peer' created: instance_<hex6>` with
`status=stopped`, `transport=ws`, `url=ws://localhost:8889` in agent.json.

### W2 — idempotent add
Repeat the same command. Expected: `already exists: ...` and still
exactly one instance agent with that name.

### W3 — `start` when reachable
With the second server running:
```
@INSTANCE_ID agent_call verb=start
```
Expected: `{ok: true, status: "running", url: "ws://localhost:8889"}`.
`agent.json.status` becomes `running`.

### W4 — `start` when unreachable
Stop the second server, then:
```
@INSTANCE_ID agent_call verb=start
```
Expected: `{ok: false, status: "unresponsive"}`. `status` persisted.

### W5 — `status` reflects reality
Bring the second server back up, call:
```
@INSTANCE_ID agent_call verb=status
```
Expected: `{status: "running"}`. Stop it and call again — expect
`unresponsive`.

### W6 — `call` proxies a dispatch tool
With the second server running:
```
@INSTANCE_ID agent_call verb=call tool=list_agents args={}
```
Expected: `{ok: true, data: [...]}` where `data` is the remote's agent
list. Prove inter-fantastic RPC works.

### W7 — `stop` in ws mode
```
@INSTANCE_ID agent_call verb=stop
```
Expected: `{ok: true, status: "stopped"}`. No subprocess touched
(ws mode owns no local process).

### Cleanup (ws)
```
delete_agent INSTANCE_ID
pkill -f "port 8889"    # stop the second fantastic
```

## SSH tests (only if user said yes)

**Requires:** user-provided `ssh_host` and `remote_dir`; SSH agent or
key auth working; `fantastic` on the remote's PATH.

### S1 — `add instance` (ssh)
```
add instance name=gpu transport=ssh ssh_host=<USER_HOST> remote_dir=<USER_DIR>
```
Expected: agent created, `transport=ssh`, no `url` yet.

### S2 — `start` spawns tunnel + remote server
```
@SSH_INSTANCE_ID agent_call verb=start
```
Expected: within ~15 s returns `{ok: true, url: "ws://127.0.0.1:<port>", pid: <pid>}`.
Agent.json populated with `tunnel_pid`, `local_port`, `url`,
`status=running`. On the local box: `lsof -iTCP:<port> -sTCP:LISTEN`
shows the ssh client listening. On the remote: `ssh <host> pgrep -af fantastic`
shows the spawned server.

### S3 — `call` over tunnel
```
@SSH_INSTANCE_ID agent_call verb=call tool=list_agents args={}
```
Expected: remote's agent list (empty on a fresh remote). Proves the
tunnel forwards WS correctly.

### S4 — `stop` kills tunnel + remote
```
@SSH_INSTANCE_ID agent_call verb=stop
```
Expected: `{ok: true, status: "stopped"}`. Tunnel process gone locally.
Remote fantastic dies (SIGHUP when tunnel closes). Verify:
`ssh <host> pgrep fantastic` returns nothing. Agent.json clears
`tunnel_pid`, `local_port`, `url`.

### Cleanup (ssh)
```
delete_agent SSH_INSTANCE_ID
```

## Pass matrix

| # | Test | Pass |
|---|---|---|
| W1 | ws add | |
| W2 | ws idempotent | |
| W3 | ws start reachable | |
| W4 | ws start unreachable | |
| W5 | ws status | |
| W6 | ws call RPC | |
| W7 | ws stop | |
| S1 | ssh add | skipped? |
| S2 | ssh start spawns tunnel | skipped? |
| S3 | ssh call over tunnel | skipped? |
| S4 | ssh stop kills tunnel+remote | skipped? |

Report which SSH host/dir was used (if any) and whether S1–S4 ran.
