"""FastAPI app factory for one web agent.

Each web agent creates its own FastAPI instance. Config (port, base_route) is
stored per-agent in agent.json and hot-reloaded on `web_configure`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    FileResponse,
    RedirectResponse,
)

from core.bus import bus
from core.dispatch import _DISPATCH, ToolResult

logger = logging.getLogger(__name__)

_SHARED_DIR = Path(__file__).resolve().parent.parent / "_web_shared"
_BUNDLES_DIR = Path(__file__).resolve().parent.parent


def _transport_script_tag(base: str) -> str:
    prefix = base.rstrip("/")
    return f'<script src="{prefix}/_fantastic/transport.js"></script>'


def _inject_transport(html: str, base: str) -> str:
    """Insert transport script as the first element in <head>."""
    tag = _transport_script_tag(base)
    # Insert right after <head>
    lower = html.lower()
    idx = lower.find("<head>")
    if idx == -1:
        # No head — prepend
        return tag + html
    insert_at = idx + len("<head>")
    return html[:insert_at] + "\n  " + tag + html[insert_at:]


def _bundle_web_dir(bundle: str) -> Path:
    """Return bundle's web/ dir. Prefer dist/ if it exists (canvas builds there)."""
    root = _BUNDLES_DIR / bundle / "web"
    dist = root / "dist"
    if dist.is_dir():
        return dist
    return root


def _headless_info_html(agent_id: str, bundle: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><title>{agent_id}</title>
<style>body{{font-family:monospace;padding:40px;background:#111;color:#ddd}} code{{background:#222;padding:2px 6px}}</style>
</head>
<body>
<h2>{agent_id}</h2>
<p>Bundle <code>{bundle}</code> is headless — no UI of its own.</p>
<p>Use a <code>fantastic_agent</code> pointed at this agent to interact.</p>
<p><code>fantastic_transport()</code> is still available if you want to call dispatch manually.</p>
</body></html>"""


def make_app(agent_id: str, engine) -> FastAPI:
    """Build a FastAPI app for one web agent.

    `agent_id` is the web agent's own id (identifies config in agent.json).
    `engine` is the core Engine instance.
    """
    web_agent = engine.get_agent(agent_id)
    base_route = (web_agent or {}).get("base_route", "") or ""
    base_route = base_route.rstrip("/")  # "" or "/admin" etc.

    app = FastAPI()

    # ─── Static: transport.js + description.json ──────────

    @app.get(f"{base_route}/_fantastic/transport.js")
    async def transport_js():
        # Built artifact from transport.ts (see bundled_agents/canvas/web scripts).
        path = _SHARED_DIR / "dist" / "transport.js"
        if not path.exists():
            return PlainTextResponse(
                "transport.js not built. Run: cd bundled_agents/canvas/web && npm run build:transport",
                status_code=503,
            )
        return FileResponse(path, media_type="application/javascript")

    @app.get(f"{base_route}/_fantastic/description.json")
    async def description_json():
        from core.protocol import describe

        return JSONResponse(describe())

    # ─── Content aliases ───────────────────────────────────

    @app.get(f"{base_route}/content/{{alias_id}}")
    async def serve_alias(alias_id: str):
        from . import tools as web_tools

        entry = web_tools.load_aliases(agent_id).get(alias_id)
        if entry is None:
            return PlainTextResponse("Unknown alias", status_code=404)
        if entry.get("type") == "url":
            return RedirectResponse(entry["url"])
        if entry.get("type") == "file":
            fp = Path(entry["path"])
            if not fp.is_absolute():
                fp = Path(engine.project_dir) / fp
            if not fp.exists():
                return PlainTextResponse("File missing", status_code=404)
            return FileResponse(fp)
        return PlainTextResponse("Malformed alias", status_code=500)

    # ─── Agent HTML entry + static assets ─────────────────

    @app.get(base_route + "/{agent_id_path}/")
    async def serve_agent_index(agent_id_path: str):
        agent = engine.get_agent(agent_id_path)
        if not agent:
            return HTMLResponse(
                f"<h1>Agent {agent_id_path} not found</h1>", status_code=404
            )
        bundle = agent.get("bundle", "")
        web_dir = _bundle_web_dir(bundle) if bundle else None
        if web_dir and (web_dir / "index.html").exists():
            html = (web_dir / "index.html").read_text(encoding="utf-8")
        else:
            html = _headless_info_html(agent_id_path, bundle)
        return HTMLResponse(_inject_transport(html, base_route))

    @app.get(base_route + "/{agent_id_path}/{asset_path:path}")
    async def serve_agent_asset(agent_id_path: str, asset_path: str):
        agent = engine.get_agent(agent_id_path)
        if not agent:
            return PlainTextResponse("Agent not found", status_code=404)
        bundle = agent.get("bundle", "")
        web_dir = _bundle_web_dir(bundle) if bundle else None
        if not web_dir:
            return PlainTextResponse("No web/ dir for bundle", status_code=404)
        # Prevent path traversal
        requested = (web_dir / asset_path).resolve()
        try:
            requested.relative_to(web_dir.resolve())
        except ValueError:
            return PlainTextResponse("Invalid path", status_code=400)
        if not requested.is_file():
            return PlainTextResponse("Not found", status_code=404)
        return FileResponse(requested)

    # ─── WebSocket: the protocol channel ──────────────────

    @app.websocket(base_route + "/{agent_id_path}/ws")
    async def ws_endpoint(ws: WebSocket, agent_id_path: str):
        agent = engine.get_agent(agent_id_path)
        if not agent:
            await ws.close(code=1008)
            return
        await ws.accept()
        target = agent_id_path

        import asyncio

        async def drain_inbox():
            try:
                async for msg in bus.recv(target):
                    await ws.send_text(json.dumps(msg, default=str))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("drain_inbox failed for %s", target)

        drain_task = asyncio.create_task(drain_inbox())

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                # web|dispatch is THIN: pure lookup+invoke, no translation.
                # Future layers (to be added ON TOP, not inside):
                # - auth / readonly ACL based on web agent's config
                # - rate limiting per connection
                # - request/response tracing / audit log
                msg_type = msg.get("type")
                if msg_type == "call":
                    tool = msg.get("tool", "")
                    args = msg.get("args", {}) or {}
                    req_id = msg.get("id", "")
                    # Handle internal bus.watch/unwatch as dispatch
                    if tool == "_bus_watch":
                        bus.watch(args.get("source", ""), target)
                        await ws.send_text(
                            json.dumps(
                                {"type": "reply", "id": req_id, "data": {"ok": True}}
                            )
                        )
                        continue
                    if tool == "_bus_unwatch":
                        bus.unwatch(args.get("source", ""), target)
                        await ws.send_text(
                            json.dumps(
                                {"type": "reply", "id": req_id, "data": {"ok": True}}
                            )
                        )
                        continue
                    fn = _DISPATCH.get(tool)
                    if fn is None:
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "id": req_id,
                                    "error": f"Unknown tool: {tool}",
                                }
                            )
                        )
                        continue
                    try:
                        from core.trace import trace

                        result = await trace("ws", target, tool, args, fn)
                        data = result.data if isinstance(result, ToolResult) else result
                        # Fire broadcasts on the bus too
                        if isinstance(result, ToolResult):
                            for bmsg in result.broadcast:
                                await bus.broadcast(bmsg)
                            for rmsg in result.reply:
                                await ws.send_text(json.dumps(rmsg, default=str))
                        await ws.send_text(
                            json.dumps(
                                {"type": "reply", "id": req_id, "data": data},
                                default=str,
                            )
                        )
                    except Exception as e:
                        logger.exception("Dispatch %s failed", tool)
                        await ws.send_text(
                            json.dumps({"type": "error", "id": req_id, "error": str(e)})
                        )
                elif msg_type == "emit":
                    event = msg.get("event", "")
                    data = msg.get("data", {}) or {}
                    await bus.emit(target, event, data)

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WS error for %s", target)
        finally:
            drain_task.cancel()
            try:
                await drain_task
            except Exception:
                pass

    return app
