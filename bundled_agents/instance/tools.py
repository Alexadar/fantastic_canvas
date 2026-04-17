"""instance bundle — a connected fantastic instance as an agent.

Every connected fantastic is one agent (bundle="instance"). Two transports:

- **ws**: `url` points to an already-running fantastic; we just open WS.
- **ssh**: we spawn `ssh -L local:127.0.0.1:remote {host} 'cd {dir} &&
  fantastic serve --port remote'`, then open WS through the tunnel.

Callers use `agent_call(target, verb, **args)` exclusively. Verbs:
`start`, `stop`, `status`, `call`. The handlers are registered as
`instance_{verb}` so the generic `agent_call` → `{bundle}_{verb}` lookup
resolves them; they are not part of the public dispatch surface by name.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shlex
import uuid
from pathlib import Path

from core.dispatch import ToolResult, register_dispatch

logger = logging.getLogger(__name__)

NAME = "instance"

_engine = None


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    global _engine
    _engine = engine
    return {}


# ─── bundle setup ────────────────────────────────────────────────────


async def on_add(
    project_dir,
    name: str = "",
    transport: str = "",
    url: str = "",
    ssh_host: str = "",
    remote_dir: str = "",
    remote_cmd: str = "fantastic",
) -> None:
    """Create ONE instance agent (connected fantastic). Explicit command only."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    display = name or "peer"

    # Idempotent by display_name.
    for a in store.list_agents():
        if a.get("bundle") == "instance" and a.get("display_name") == display:
            print(f"  instance '{display}' already exists: {a['id']}")
            return

    # Infer transport from args.
    if not transport:
        transport = "ssh" if ssh_host else "ws"

    if transport not in ("ws", "ssh"):
        print(f"  [error] transport must be 'ws' or 'ssh' (got {transport!r})")
        return
    if transport == "ws" and not url:
        print("  [error] ws transport requires url=ws://host:port")
        return
    if transport == "ssh" and not ssh_host:
        print("  [error] ssh transport requires ssh_host=...")
        return

    agent = store.create_agent(bundle="instance")
    meta = {
        "display_name": display,
        "transport": transport,
        "status": "stopped",
    }
    if transport == "ws":
        meta["url"] = url
    else:
        meta["ssh_host"] = ssh_host
        meta["remote_dir"] = remote_dir
        meta["remote_cmd"] = remote_cmd
    store.update_agent_meta(agent["id"], **meta)
    print(f"  instance '{display}' created: {agent['id']}  transport={transport}")


# ─── helpers ─────────────────────────────────────────────────────────


async def _ws_open_probe(url: str, timeout: float = 3.0) -> bool:
    """Open a WS to url, close immediately. Return True iff handshake succeeds."""
    import websockets

    try:
        async with asyncio.timeout(timeout):
            async with websockets.connect(url):
                return True
    except Exception:
        return False


async def _ws_rpc(url: str, tool: str, args: dict, timeout: float = 30.0) -> dict:
    """Open a WS, send one `{type:call}`, await the matching reply."""
    import websockets

    rid = str(uuid.uuid4())
    async with asyncio.timeout(timeout):
        async with websockets.connect(url) as ws:
            await ws.send(
                json.dumps({"type": "call", "tool": tool, "args": args, "id": rid})
            )
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") != rid:
                    continue
                if msg["type"] == "reply":
                    return msg.get("data", {})
                if msg["type"] == "error":
                    return {"error": msg.get("error", "unknown")}


def _tunnel_command(local_port: int, remote_port: int, agent: dict) -> str:
    """Build the `ssh -L …` command string for the tunnel."""
    host = agent["ssh_host"]
    rdir = agent.get("remote_dir", "")
    rcmd = agent.get("remote_cmd", "fantastic")
    # shlex.quote prevents remote_dir from breaking out of the outer shell.
    remote = f"cd {shlex.quote(rdir)} && " if rdir else ""
    remote += f"{rcmd} serve --port {remote_port}"
    return (
        f"ssh -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 "
        f"-L {local_port}:127.0.0.1:{remote_port} {shlex.quote(host)} "
        f"{shlex.quote(remote)}"
    )


def _find_free_local_port(start: int = 49200) -> int:
    import socket

    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no free local port found")


# ─── verb handlers ──────────────────────────────────────────────────


@register_dispatch("instance_start")
async def _start(agent_id: str = "", **_kw) -> ToolResult:
    agent = _engine.get_agent(agent_id)
    if not agent or agent.get("bundle") != "instance":
        return ToolResult(data={"error": f"{agent_id} is not an instance agent"})

    transport = agent.get("transport", "")
    if transport == "ws":
        url = agent.get("url", "")
        if not url:
            return ToolResult(data={"error": "url not set"})
        ok = await _ws_open_probe(url)
        status = "running" if ok else "unresponsive"
        _engine.update_agent_meta(agent_id, status=status)
        return ToolResult(
            data={"ok": ok, "agent_id": agent_id, "status": status, "url": url},
            broadcast=[
                {"type": "agent_updated", "agent_id": agent_id, "status": status}
            ],
        )

    if transport == "ssh":
        local_port = _find_free_local_port()
        remote_port = (
            local_port  # use same number remotely (simpler; remote picks if busy)
        )
        cmd = _tunnel_command(local_port, remote_port, agent)
        logger.info("instance_start: spawning tunnel: %s", cmd)
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        url = f"ws://127.0.0.1:{local_port}"
        # Poll until tunnel + remote server both up, or timeout.
        ok = False
        for _ in range(30):
            await asyncio.sleep(0.5)
            if proc.returncode is not None:
                break
            if await _ws_open_probe(url, timeout=1.0):
                ok = True
                break
        if not ok:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            return ToolResult(
                data={"error": "tunnel did not come up in 15s", "agent_id": agent_id}
            )
        _engine.update_agent_meta(
            agent_id,
            status="running",
            url=url,
            local_port=local_port,
            tunnel_pid=proc.pid,
        )
        return ToolResult(
            data={"ok": True, "agent_id": agent_id, "url": url, "pid": proc.pid},
            broadcast=[
                {"type": "agent_updated", "agent_id": agent_id, "status": "running"}
            ],
        )

    return ToolResult(data={"error": f"unknown transport {transport!r}"})


@register_dispatch("instance_stop")
async def _stop(agent_id: str = "", **_kw) -> ToolResult:
    agent = _engine.get_agent(agent_id)
    if not agent:
        return ToolResult(data={"error": f"{agent_id} not found"})

    if agent.get("transport") == "ssh":
        pid = agent.get("tunnel_pid")
        if pid:
            import os
            import signal as _sig

            try:
                os.kill(int(pid), _sig.SIGTERM)
            except ProcessLookupError:
                pass
        _engine.update_agent_meta(
            agent_id, status="stopped", tunnel_pid=None, local_port=None, url=""
        )
    else:
        _engine.update_agent_meta(agent_id, status="stopped")

    return ToolResult(
        data={"ok": True, "agent_id": agent_id, "status": "stopped"},
        broadcast=[
            {"type": "agent_updated", "agent_id": agent_id, "status": "stopped"}
        ],
    )


@register_dispatch("instance_status")
async def _status(agent_id: str = "", **_kw) -> ToolResult:
    agent = _engine.get_agent(agent_id)
    if not agent:
        return ToolResult(data={"error": f"{agent_id} not found"})
    url = agent.get("url", "")
    if not url:
        return ToolResult(data={"agent_id": agent_id, "status": "stopped"})
    ok = await _ws_open_probe(url)
    status = "running" if ok else "unresponsive"
    _engine.update_agent_meta(agent_id, status=status)
    return ToolResult(data={"agent_id": agent_id, "status": status, "url": url})


@register_dispatch("instance_call")
async def _call(
    agent_id: str = "", tool: str = "", args: dict | None = None, **_kw
) -> ToolResult:
    """Proxy a dispatch call to the remote instance over its WS."""
    agent = _engine.get_agent(agent_id)
    if not agent:
        return ToolResult(data={"error": f"{agent_id} not found"})
    url = agent.get("url", "")
    if not url:
        return ToolResult(data={"error": "instance not started (no url)"})
    if not tool:
        return ToolResult(data={"error": "tool required"})
    try:
        data = await _ws_rpc(url, tool, args or {})
    except Exception as e:
        return ToolResult(data={"error": f"{type(e).__name__}: {e}"})
    return ToolResult(
        data={"ok": True, "agent_id": agent_id, "tool": tool, "data": data}
    )
