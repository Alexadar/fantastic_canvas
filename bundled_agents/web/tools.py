"""Web agent bundle — HTTP/WS transport, serves all agent UIs with injected transport.

Also owns per-web-agent **content aliases** (`/content/{alias_id}` → file
or URL redirect). Each web agent's aliases live in a sidecar
`.fantastic/agents/{web_id}/aliases.json` and are exposed via the three
`agent_call` verbs `alias` / `aliases` / `unalias` (handler names
`web_alias`, `web_aliases`, `web_unalias`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path

from core.dispatch import (
    ToolResult,
    register_dispatch as _dispatch_deco,
    register_tool as _tool_deco,
)

logger = logging.getLogger(__name__)

NAME = "web"

_engine = None
_serve_tasks: dict[str, asyncio.Task] = {}  # agent_id → uvicorn task
_should_restart: set[str] = set()
# In-memory alias map per web agent. Loaded from sidecar on first use;
# also handed to the FastAPI app factory so HTTP handlers can read it.
_aliases_cache: dict[str, dict[str, dict]] = {}


# ─── alias storage ─────────────────────────────────────────────────


def _aliases_path(web_id: str) -> Path:
    return Path(_engine.project_dir) / ".fantastic" / "agents" / web_id / "aliases.json"


def load_aliases(web_id: str) -> dict[str, dict]:
    """Return the in-memory alias dict for `web_id`, loading from disk if first use."""
    cached = _aliases_cache.get(web_id)
    if cached is not None:
        return cached
    path = _aliases_path(web_id)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            # Only persistent entries survive across restarts.
            loaded = {k: v for k, v in data.items() if v.get("persistent")}
        except Exception:
            loaded = {}
    else:
        loaded = {}
    _aliases_cache[web_id] = loaded
    return loaded


def _save_aliases(web_id: str) -> None:
    path = _aliases_path(web_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_aliases_cache.get(web_id, {})))


async def serve(agent_id: str) -> None:
    """Long-running task: serves this web agent's FastAPI, restarts on config change."""
    import uvicorn
    from .app import make_app

    while True:
        if _engine is None:
            await asyncio.sleep(1)
            continue
        agent = _engine.get_agent(agent_id)
        if not agent:
            logger.warning("web agent %s vanished, exiting serve loop", agent_id)
            return
        port = int(agent.get("port", 8888))
        app = make_app(agent_id, _engine)
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
        server = uvicorn.Server(config)
        logger.info("web agent %s serving on port %d", agent_id, port)
        try:
            await server.serve()
        except asyncio.CancelledError:
            if server.started:
                server.should_exit = True
                try:
                    await asyncio.wait_for(server.shutdown(), timeout=3)
                except Exception:
                    pass
            raise
        except Exception:
            logger.exception("uvicorn crashed for %s", agent_id)
            await asyncio.sleep(1)

        if agent_id in _should_restart:
            _should_restart.discard(agent_id)
            logger.info("web agent %s restarting due to config change", agent_id)
            continue
        break


@_dispatch_deco("web_configure")
async def _configure(
    agent_id: str = "",
    port: int | None = None,
    base_route: str | None = None,
    **_kw,
) -> ToolResult:
    if not agent_id:
        return ToolResult(data={"error": "agent_id required"})
    agent = _engine.get_agent(agent_id)
    if not agent or agent.get("bundle") != "web":
        return ToolResult(data={"error": f"{agent_id} is not a web agent"})

    updates: dict = {}
    if port is not None:
        updates["port"] = int(port)
    if base_route is not None:
        updates["base_route"] = base_route.strip()
    if not updates:
        return ToolResult(data={"ok": True, "no_changes": True})

    _engine.update_agent_meta(agent_id, **updates)

    # Signal restart + cancel current task (serve loop will re-read config)
    _should_restart.add(agent_id)
    task = _serve_tasks.get(agent_id)
    if task and not task.done():
        task.cancel()

    return ToolResult(
        data={"ok": True, "agent_id": agent_id, **updates},
        broadcast=[{"type": "agent_updated", "agent_id": agent_id, **updates}],
    )


# ─── alias verb handlers ────────────────────────────────────────────


def _require_web_agent(agent_id: str) -> tuple[dict | None, ToolResult | None]:
    if not agent_id:
        return None, ToolResult(data={"error": "agent_id required"})
    agent = _engine.get_agent(agent_id)
    if not agent or agent.get("bundle") != "web":
        return None, ToolResult(data={"error": f"{agent_id} is not a web agent"})
    return agent, None


def _alias_path_str(alias_id: str) -> str:
    return f"/content/{alias_id}"


@_dispatch_deco("web_alias")
async def _alias(
    agent_id: str = "",
    kind: str = "",
    path: str = "",
    url: str = "",
    persistent: bool = True,
    **_kw,
) -> ToolResult:
    _, err = _require_web_agent(agent_id)
    if err:
        return err
    if kind not in ("file", "url"):
        return ToolResult(data={"error": "kind must be 'file' or 'url'"})
    aliases = load_aliases(agent_id)
    alias_id = secrets.token_hex(4)
    if kind == "file":
        if not path:
            return ToolResult(data={"error": "path required for kind='file'"})
        abs_path = os.path.abspath(path)
        try:
            rel = os.path.relpath(abs_path, str(_engine.project_dir))
            if not rel.startswith(".."):
                entry = {
                    "type": "file",
                    "path": rel,
                    "relative": True,
                    "persistent": persistent,
                }
            else:
                entry = {"type": "file", "path": abs_path, "persistent": persistent}
        except ValueError:
            entry = {"type": "file", "path": abs_path, "persistent": persistent}
    else:
        if not url:
            return ToolResult(data={"error": "url required for kind='url'"})
        entry = {"type": "url", "url": url, "persistent": persistent}
    aliases[alias_id] = entry
    _save_aliases(agent_id)
    return ToolResult(
        data={"alias_id": alias_id, "alias_path": _alias_path_str(alias_id)}
    )


@_dispatch_deco("web_aliases")
async def _aliases(agent_id: str = "", **_kw) -> ToolResult:
    _, err = _require_web_agent(agent_id)
    if err:
        return err
    out = []
    for aid, entry in load_aliases(agent_id).items():
        info = {
            "alias_id": aid,
            "alias_path": _alias_path_str(aid),
            "type": entry.get("type"),
            "persistent": entry.get("persistent", False),
        }
        if entry.get("type") == "file":
            info["path"] = entry.get("path", "")
            info["relative"] = entry.get("relative", False)
        elif entry.get("type") == "url":
            info["url"] = entry.get("url", "")
        out.append(info)
    return ToolResult(data={"aliases": out})


@_dispatch_deco("web_unalias")
async def _unalias(agent_id: str = "", alias_id: str = "", **_kw) -> ToolResult:
    _, err = _require_web_agent(agent_id)
    if err:
        return err
    if not alias_id:
        return ToolResult(data={"error": "alias_id required"})
    aliases = load_aliases(agent_id)
    removed = aliases.pop(alias_id, None) is not None
    if removed:
        _save_aliases(agent_id)
    return ToolResult(data={"removed": removed, "alias_id": alias_id})


@_tool_deco("web_configure")
async def web_configure(agent_id: str, port: int = 0, base_route: str = "") -> dict:
    """Update a web agent's port or base_route (hot-reloads uvicorn).

    Args:
        agent_id: The web agent to configure.
        port: New port (0 = unchanged).
        base_route: New base route prefix (empty string = unchanged marker? use explicit).
    """
    kwargs: dict = {"agent_id": agent_id}
    if port:
        kwargs["port"] = port
    if base_route is not None:
        kwargs["base_route"] = base_route
    tr = await _configure(**kwargs)
    return tr.data


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    global _engine
    _engine = engine

    # Hook: announce readiness + list canvas URLs once all bundles have loaded.
    from core.tools._state import _on_subagents_loaded

    _on_subagents_loaded.append(_announce_ready)

    return {}


def _announce_ready(engine) -> None:
    """Called after init_tools completes. Prints summary + canvas URLs."""
    from core import conversation

    agents = engine.store.list_agents()
    web_agents = [a for a in agents if a.get("bundle") == "web"]
    canvas_agents = [a for a in agents if a.get("bundle") == "canvas"]

    def say(who: str, msg: str):
        print(conversation.format_entry(conversation.say(who, msg)))

    say("web", "all subagents loaded")

    if not web_agents:
        return
    wa = web_agents[0]
    host = "localhost"
    port = int(wa.get("port", 8888))
    base = (wa.get("base_route") or "").rstrip("/")
    for c in canvas_agents:
        url = f"http://{host}:{port}{base}/{c['id']}/"
        say("web", f"Canvas {c['id']} url: {url}")


async def on_add(project_dir, name: str = "", working_dir: str = "") -> None:
    """Invoked ONLY by the explicit `add web` command. Creates one web agent
    with the given display name and starts its uvicorn task. Never auto-runs."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    display = name or "main"
    for a in store.list_agents():
        if a.get("bundle") == "web" and a.get("display_name") == display:
            print(f"  web '{display}' already exists: {a['id']}")
            return
    agent = store.create_agent(bundle="web")
    store.update_agent_meta(agent["id"], port=8888, base_route="", display_name=display)
    if agent["id"] not in _serve_tasks:
        _serve_tasks[agent["id"]] = asyncio.create_task(serve(agent["id"]))
    print(f"  web '{display}' created: {agent['id']}  http://localhost:8888/")
    # Let serve() bind the port before returning
    await asyncio.sleep(0.8)
    task = _serve_tasks.get(agent["id"])
    if task and task.done():
        exc = task.exception()
        if exc:
            print(f"  [serve error] {exc!r}")
