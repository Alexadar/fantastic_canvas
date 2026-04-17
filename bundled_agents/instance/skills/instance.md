# `instance` bundle — connected fantastic instances

One agent per connected fantastic instance. Two transports (`ws`, `ssh`).
All verbs go through `agent_call`.

## Add an instance

```
# WS instance (already running elsewhere)
add instance name=box-a transport=ws url=ws://other-host:8888

# SSH instance (spawn + tunnel)
add instance name=gpu transport=ssh ssh_host=gpu-box remote_dir=/home/me/proj
```

Creates an `instance_<hex6>` agent with the connection config persisted
in its `agent.json`. Transport is inferred from args if omitted
(`ssh_host` set → ssh, else ws).

## Verbs (via `agent_call`)

```
# start (ws: health-check; ssh: spawn tunnel + remote server)
@instance_<id> agent_call verb=start

# status
@instance_<id> agent_call verb=status

# RPC a tool on the remote instance
@instance_<id> agent_call verb=call tool=list_agents args={}

# stop (ssh: kill tunnel → remote SIGHUP; ws: no-op)
@instance_<id> agent_call verb=stop
```

## Lifecycle

- **Add** → agent created, `status=stopped`.
- **start** → for `ssh`, spawns `ssh -L L:127.0.0.1:R host 'cd dir && fantastic serve --port R'`,
  polls WS until handshake. Writes `tunnel_pid`, `local_port`, `url=ws://127.0.0.1:L`.
  For `ws`, just probes `url`.
- **call** → opens a fresh WS to `url`, sends one `{type:"call",tool,args,id}`,
  returns the matched `{type:"reply"}` data.
- **stop** → ssh: `SIGTERM` the tunnel (remote server gets SIGHUP and dies).
  ws: only marks status.
- **delete the agent** (`delete_agent`) → removes the instance record entirely.

## Notes

- Registry: each instance is an ordinary agent; its `agent.json` holds
  all connection metadata (transport, url, ssh_host, tunnel_pid,
  local_port, status). No separate instances file.
- No `register` vs `launch` distinction. Adding the agent IS registering;
  `agent_call verb=start` IS launching.
- `url` for ssh is populated on `start`, cleared on `stop`.
- Local port is chosen from 49200+ by probing; remote port is the same number.
