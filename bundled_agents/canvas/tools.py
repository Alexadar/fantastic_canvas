"""Canvas bundle — agent layout, output, VFX, spatial discovery, and canvas handbook tools.

Layout is now stored in each agent's agent.json (x/y/width/height). This bundle
provides canvas-specific tools (move, resize, VFX, spatial discovery) and auto-parents
new agents to a canvas when only one canvas exists.

Multiple canvas instances are supported — each is a real agent (bundle="canvas")
with its own display_name and VFX state.
"""

import math
from pathlib import Path

from core.dispatch import ToolResult
from core.tools._agents import (
    _rename_agent, _update_agent, _post_output, _refresh_agent,
)

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_BUNDLE_DIR = Path(__file__).resolve().parent

# Module-level engine ref (set in register_tools)
_engine = None


def _seed_default_vfx(agent_dir: Path) -> None:
    """Copy default_vfx.js into a canvas agent dir if scene_vfx.js doesn't exist."""
    vfx_dest = agent_dir / "scene_vfx.js"
    if vfx_dest.exists():
        return
    src = _BUNDLE_DIR / "default_vfx.js"
    if src.exists():
        import shutil
        shutil.copy2(src, vfx_dest)


def on_add(project_dir: str, name: str = "", working_dir: str = "") -> None:
    """Called by `fantastic add canvas` — creates a canvas agent with the given name."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    display = name or "main"
    # Check name uniqueness among canvas agents
    for a in store.list_agents():
        if a.get("bundle") == "canvas" and a.get("display_name") == display:
            print(f"  Canvas '{display}' already exists: {a['id']}")
            return
    agent = store.create_agent(bundle="canvas")
    meta: dict = {"display_name": display, "is_container": True}
    if working_dir:
        meta["working_dir"] = working_dir
    store.update_agent_meta(agent["id"], **meta)
    # Seed default VFX
    _seed_default_vfx(store.agents_dir / agent["id"])
    print(f"  Canvas '{display}' created: {agent['id']}")


async def _get_handbook_canvas(skill: str = "") -> ToolResult:
    if skill:
        skill_file = _SKILLS_DIR / f"{skill}.md"
        if skill_file.exists():
            return ToolResult(data={"text": f"# SKILL: {skill}\n\n{skill_file.read_text()}"})
        available = [p.stem for p in _SKILLS_DIR.glob("*.md")] if _SKILLS_DIR.exists() else []
        avail_str = ", ".join(sorted(available)) or "(none)"
        return ToolResult(data={"error": f"Skill '{skill}' not found. Available: {avail_str}"})
    available = sorted(p.stem for p in _SKILLS_DIR.glob("*.md")) if _SKILLS_DIR.exists() else []
    return ToolResult(data={"text": "Canvas skills: " + ", ".join(available) if available else "No canvas skills found."})


# ─── Layout-aware inner functions (for _DISPATCH) ────────────────────────


async def _move_agent(agent_id: str = "", x: float = 0, y: float = 0) -> ToolResult:
    if not _engine.update_agent_meta(agent_id, x=round(x), y=round(y)):
        return ToolResult(data={"error": f"Agent {agent_id} not found"})
    return ToolResult(
        data={"agent_id": agent_id, "x": x, "y": y},
        broadcast=[
            {"type": "agent_moved", "agent_id": agent_id, "x": x, "y": y},
        ],
    )


async def _resize_agent(
    agent_id: str = "",
    width: float | None = None,
    height: float | None = None,
) -> ToolResult:
    kwargs: dict[str, float] = {}
    if width is not None:
        kwargs["width"] = round(max(250, width))
    if height is not None:
        kwargs["height"] = round(max(100, height))
    if not kwargs:
        return ToolResult(data={"error": "Provide at least one of width or height"})
    if not _engine.update_agent_meta(agent_id, **kwargs):
        return ToolResult(data={"error": f"Agent {agent_id} not found"})
    agent = _engine.get_agent(agent_id)
    return ToolResult(
        data={"agent_id": agent_id, "width": agent["width"], "height": agent["height"]},
        broadcast=[
            {"type": "agent_resized", "agent_id": agent_id, **kwargs},
        ],
    )


def _rect_distance(a: dict, b: dict) -> float:
    """Minimum edge-to-edge distance between two axis-aligned rectangles."""
    a_left, a_right = a["x"], a["x"] + a["width"]
    a_top, a_bottom = a["y"], a["y"] + a["height"]
    b_left, b_right = b["x"], b["x"] + b["width"]
    b_top, b_bottom = b["y"], b["y"] + b["height"]
    dx = max(0, max(a_left - b_right, b_left - a_right))
    dy = max(0, max(a_top - b_bottom, b_top - a_bottom))
    return math.sqrt(dx * dx + dy * dy)


async def _spatial_discovery(agent_id: str = "", radius: float | None = None) -> ToolResult:
    target = _engine.get_agent(agent_id)
    if not target:
        return ToolResult(data=[])
    parent = target.get("parent")
    all_agents = _engine.store.list_agents()
    results = []
    for a in all_agents:
        if a["id"] == agent_id:
            continue
        if a.get("parent") != parent:
            continue
        dist = _rect_distance(target, a)
        if radius is not None and dist > radius:
            continue
        results.append({
            "agent_id": a["id"],
            "distance": round(dist, 1),
            "x": a.get("x", 0), "y": a.get("y", 0),
            "width": a.get("width", 800), "height": a.get("height", 600),
        })
    results.sort(key=lambda r: r["distance"])
    if radius is None:
        return ToolResult(data=results[:1])
    return ToolResult(data=results)


# ─── VFX inner functions (owned by canvas bundle) ──────────────────────


def _find_canvas_agent_dir(canvas_name: str = "") -> Path | None:
    """Find canvas agent directory by name. Falls back to first canvas."""
    agents = _engine.store.list_agents()
    canvases = [a for a in agents if a.get("bundle") == "canvas"]
    if canvas_name:
        for c in canvases:
            if c.get("display_name") == canvas_name:
                return _engine.store.agents_dir / c["id"]
    if canvases:
        return _engine.store.agents_dir / canvases[0]["id"]
    return None


async def _scene_vfx_data(data: dict, canvas_name: str = "") -> ToolResult:
    return ToolResult(
        data={"ok": True},
        broadcast=[{"type": "scene_vfx_data", "data": data, "canvas_name": canvas_name}],
    )


async def _scene_vfx(js_code: str, canvas_name: str = "") -> ToolResult:
    canvas_dir = _find_canvas_agent_dir(canvas_name)
    if canvas_dir:
        (canvas_dir / "scene_vfx.js").write_text(js_code, encoding="utf-8")
    return ToolResult(
        data={"ok": True},
        broadcast=[{"type": "scene_vfx_updated", "js": js_code, "canvas_name": canvas_name}],
    )


def _get_scene_vfx() -> str | None:
    """Read scene_vfx.js from first canvas agent dir, falling back to bundled default."""
    canvas_dir = _find_canvas_agent_dir()
    if canvas_dir:
        # Primary: scene_vfx.js
        path = canvas_dir / "scene_vfx.js"
        if path.exists():
            return path.read_text(encoding="utf-8")
        # Migration fallback: canvasbg.js (old 2D VFX — may not work in THREE.js context)
        legacy = canvas_dir / "canvasbg.js"
        if legacy.exists():
            return legacy.read_text(encoding="utf-8")
    default = _BUNDLE_DIR / "default_vfx.js"
    if default.exists():
        return default.read_text(encoding="utf-8")
    return None


def _register_server_hooks(engine):
    """Register canvas-specific server hooks (routes, broadcast resolver, lifespan)."""
    from core.server._state import register_route_hook, register_broadcast_resolver, register_lifespan_hook

    # ─── Broadcast resolver: route messages to the correct canvas ──
    def _resolve_canvas_broadcast(message: dict) -> str:
        aid = message.get("agent_id", "")
        if not aid:
            return ""
        agent = engine.store.get_agent(aid)
        if not agent:
            return ""
        if agent.get("is_container"):
            return agent.get("display_name", "")
        parent_id = agent.get("parent", "")
        if not parent_id:
            return ""
        parent = engine.store.get_agent(parent_id)
        return parent.get("display_name", "") if parent and parent.get("is_container") else ""

    register_broadcast_resolver(_resolve_canvas_broadcast)

    # ─── Routes: serve canvas web UI ──
    def _canvas_routes(app, state):
        import mimetypes as _mt
        from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
        from starlette.responses import Response
        from core._paths import web_dist_dir, default_shell_path

        def _list_canvases():
            return [a for a in state.engine.store.list_agents() if a.get("is_container")]

        def _find_canvas(name):
            return next((a for a in state.engine.store.list_agents()
                         if a.get("is_container") and a.get("display_name") == name), None)

        @app.get("/canvas/{canvas_name}")
        async def serve_canvas_redirect(canvas_name: str):
            return RedirectResponse(url=f"/canvas/{canvas_name}/", status_code=301)

        @app.get("/canvas/{canvas_name}/")
        @app.get("/canvas/{canvas_name}/{path:path}")
        async def serve_canvas(canvas_name: str, path: str = ""):
            canvas = _find_canvas(canvas_name)
            if not canvas:
                return Response(status_code=404, content=f"Canvas '{canvas_name}' not found")
            _wd = web_dist_dir()
            if not _wd.exists():
                return Response(status_code=503, content="Canvas web UI not built")
            if not path or not (_wd / path).exists():
                return FileResponse(str(_wd / "index.html"), media_type="text/html")
            asset_path = _wd / path
            if asset_path.exists() and asset_path.is_file():
                mt, _ = _mt.guess_type(str(asset_path))
                return FileResponse(str(asset_path), media_type=mt or "application/octet-stream")
            return Response(status_code=404, content=f"Asset not found: {path}")

        # Root page — adaptive: single canvas redirect, multi-canvas links, or default shell
        has_canvas = bool(_list_canvases()) and web_dist_dir().exists()
        if has_canvas:
            @app.get("/", name="root_page")
            async def _root_page():
                canvases = _list_canvases()
                if len(canvases) == 1:
                    name = canvases[0].get("display_name") or canvases[0]["id"]
                    return RedirectResponse(url=f"/canvas/{name}", status_code=302)
                links = ""
                if canvases:
                    links += "<h2>Canvas</h2><ul>" + "\n".join(
                        f'<li><a href="/canvas/{c.get("display_name") or c["id"]}">'
                        f'{c.get("display_name") or c["id"]}</a></li>'
                        for c in canvases
                    ) + "</ul>"
                if links:
                    return HTMLResponse(
                        f"<html><body style='font-family:monospace;padding:2em'>"
                        f"<h1>Fantastic</h1>{links}</body></html>"
                    )
                return HTMLResponse(
                    "<html><body style='font-family:monospace;padding:2em'>"
                    "<h1>Fantastic</h1><p>No canvases.</p></body></html>"
                )
        else:
            _shell = default_shell_path()
            if _shell.exists():
                @app.get("/", name="default_shell")
                async def _default_shell():
                    return FileResponse(str(_shell), media_type="text/html")

    register_route_hook(_canvas_routes)

    # ─── Lifespan: announce canvas URLs ──
    import asyncio
    import logging
    import os

    _logger = logging.getLogger(__name__)

    async def _canvas_startup(state, broadcast_fn):
        server_port = os.getenv("SERVER_PORT", "8888")
        canvases = [a for a in state.engine.store.list_agents() if a.get("is_container")]
        if not canvases:
            return
        _logger.info(f"canvas web ui on http://localhost:{server_port}")
        from core.tools._conversation import _core_chat_message
        for c in canvases:
            name = c.get("display_name") or c["id"]
            url = f"http://localhost:{server_port}/canvas/{name}"
            asyncio.get_event_loop().call_soon(
                lambda msg=url, n=name: asyncio.ensure_future(_core_chat_message(who=n, message=msg))
            )

    register_lifespan_hook(_canvas_startup)


def register_dispatch():
    """Return inner dispatch functions for _DISPATCH table."""
    if _engine is None:
        return {}
    return {
        "get_handbook_canvas": _get_handbook_canvas,
        "move_agent": _move_agent,
        "resize_agent": _resize_agent,
        "spatial_discovery": _spatial_discovery,
        "scene_vfx": _scene_vfx,
        "scene_vfx_data": _scene_vfx_data,
    }


def register_tools(engine, fire_broadcasts, process_runner=None):
    """Register canvas tools."""
    global _engine
    _engine = engine
    tools = {}

    # ─── At least one canvas agent must exist ──
    canvas_agent = engine.store.find_by_bundle("canvas")
    if canvas_agent is None:
        raise RuntimeError("Canvas bundle loaded but canvas agent not found. Run: fantastic add canvas")

    # ─── Server hooks: routes, broadcast resolver, lifespan ──
    _register_server_hooks(engine)

    # ─── Seed default VFX for existing canvases that don't have it yet ──
    for a in engine.store.list_agents():
        if a.get("bundle") == "canvas":
            _seed_default_vfx(engine.store.agents_dir / a["id"])

    # ─── Auto-parent hook: new agents without parent get assigned to a canvas ──
    from core.tools import _state

    def _auto_parent(agent_id: str, agent_dict: dict) -> None:
        """If agent has no parent and isn't a canvas itself, assign to a canvas.

        Also sets default layout for canvas children that don't have layout yet.
        Raises ValueError when multiple canvases exist and no parent is specified.
        """
        if agent_dict.get("parent") or agent_dict.get("bundle") == "canvas":
            # Set default layout for canvas children that already have a parent
            if agent_dict.get("parent") and agent_dict.get("bundle") != "canvas":
                defaults = {}
                for k, v in [("x", 0), ("y", 0), ("width", 800), ("height", 600)]:
                    if k not in agent_dict:
                        defaults[k] = v
                if defaults:
                    engine.store.update_agent_meta(agent_id, **defaults)
                    agent_dict.update(defaults)
            return
        canvases = [a for a in engine.store.list_agents() if a.get("bundle") == "canvas"]
        if len(canvases) == 1:
            engine.store.update_agent_meta(agent_id, parent=canvases[0]["id"])
            agent_dict["parent"] = canvases[0]["id"]
            # Set default layout
            defaults = {}
            for k, v in [("x", 0), ("y", 0), ("width", 800), ("height", 600)]:
                if k not in agent_dict:
                    defaults[k] = v
            if defaults:
                engine.store.update_agent_meta(agent_id, **defaults)
                agent_dict.update(defaults)
        elif len(canvases) > 1:
            names = [c.get("display_name", c["id"]) for c in canvases]
            raise ValueError(
                f"Multiple canvases exist ({', '.join(names)}). "
                f"Specify parent= explicitly."
            )

    _state._on_agent_created.append(_auto_parent)

    # ─── Enrich hook: set layout defaults when reading agents ──
    def _enrich_layout(agent_id: str, agent_dict: dict) -> None:
        """Set default layout fields for canvas-scoped agents."""
        parent = agent_dict.get("parent")
        is_canvas = agent_dict.get("bundle") == "canvas"
        if is_canvas or parent:
            agent_dict.setdefault("x", 0)
            agent_dict.setdefault("y", 0)
            agent_dict.setdefault("width", 800)
            agent_dict.setdefault("height", 600)

    engine.store.on_enrich_agent(_enrich_layout)

    # ─── State enrichment hook: add scene_vfx_js per canvas + top-level ──
    def _enrich_state(state: dict) -> None:
        # Per-canvas VFX on agent dicts
        for a in state.get("agents", []):
            if a.get("bundle") == "canvas":
                canvas_dir = _engine.store.agents_dir / a["id"]
                # Primary: scene_vfx.js, fallback: canvasbg.js (migration)
                vfx_path = canvas_dir / "scene_vfx.js"
                if not vfx_path.exists():
                    vfx_path = canvas_dir / "canvasbg.js"
                if vfx_path.exists():
                    a["scene_vfx_js"] = vfx_path.read_text(encoding="utf-8")
                else:
                    default = _BUNDLE_DIR / "default_vfx.js"
                    if default.exists():
                        a["scene_vfx_js"] = default.read_text(encoding="utf-8")
        # Top-level scene_vfx_js (first canvas)
        scene_vfx_js = _get_scene_vfx()
        if scene_vfx_js is not None:
            state["scene_vfx_js"] = scene_vfx_js

    engine.on_enrich_state(_enrich_state)

    # ─── Tool wrappers ────────────────────────────────────────────

    async def move_agent(agent_id: str, x: float, y: float) -> dict:
        """Move an agent to a new position on the canvas.

        Args:
            agent_id: The agent to move.
            x: New horizontal position.
            y: New vertical position.
        """
        tr = await _move_agent(agent_id, x, y)
        await fire_broadcasts(tr)
        return tr.data
    tools["move_agent"] = move_agent

    async def resize_agent(
        agent_id: str,
        width: float | None = None,
        height: float | None = None,
    ) -> dict:
        """Resize an agent on the canvas.

        Args:
            agent_id: The agent to resize.
            width: New width in pixels (min 250). Omit to keep current.
            height: New height in pixels (min 100). Omit to keep current.
        """
        tr = await _resize_agent(agent_id, width=width, height=height)
        await fire_broadcasts(tr)
        return tr.data
    tools["resize_agent"] = resize_agent

    async def rename_agent(agent_id: str, display_name: str) -> dict:
        """Set the display name shown in an agent's header on the canvas.

        Args:
            agent_id: The agent to rename.
            display_name: New display name (empty string resets to default).
        """
        tr = await _rename_agent(agent_id, display_name)
        await fire_broadcasts(tr)
        return tr.data
    tools["rename_agent"] = rename_agent

    async def update_agent(agent_id: str, options: dict) -> dict:
        """Update agent properties. Only provided fields are changed.

        Args:
            agent_id: The agent to update.
            options: Properties to update (e.g. {"display_name": "My Agent", "autostart": true, "delete_lock": true}).
        """
        tr = await _update_agent(agent_id, options=options)
        if "error" in tr.data:
            return tr.data
        await fire_broadcasts(tr)
        return tr.data
    tools["update_agent"] = update_agent

    async def post_output(agent_id: str, html: str) -> str:
        """Push HTML output to an agent on the canvas.

        Args:
            agent_id: The agent to update.
            html: HTML content to display in the agent.
        """
        tr = await _post_output(agent_id, html)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return f"Output posted to agent {agent_id}"
    tools["post_output"] = post_output

    async def refresh_agent(agent_id: str) -> str:
        """Refresh an agent. Restarts terminal, reloads iframe, or re-fetches files.

        Args:
            agent_id: The agent to refresh.
        """
        tr = await _refresh_agent(agent_id)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        await fire_broadcasts(tr)
        action = tr.data.get("action", "")
        if action == "process_restarted":
            return f"Process in {agent_id} restarted"
        return f"Agent {agent_id} refreshed"
    tools["refresh_agent"] = refresh_agent

    async def scene_vfx(js_code: str, canvas_name: str = "") -> str:
        """Set the canvas scene VFX (THREE.js). Live-reloads on all clients.

        The code receives: scene, THREE, camera, renderer, clock.
        Use `this.onFrame = (delta, elapsed) => { ... }` for animation loops.
        Return a cleanup function to dispose resources on reload.

        Example:
            const geo = new THREE.TorusKnotGeometry(20, 6, 64, 16)
            const mat = new THREE.MeshStandardMaterial({ color: '#ff4488', wireframe: true })
            const mesh = new THREE.Mesh(geo, mat)
            scene.add(mesh)
            this.onFrame = (dt, t) => { mesh.rotation.y += 0.01 }
            return () => { scene.remove(mesh); geo.dispose(); mat.dispose() }

        Args:
            js_code: JavaScript code for the VFX animation.
            canvas_name: Target canvas name. Empty = first canvas.
        """
        tr = await _scene_vfx(js_code, canvas_name=canvas_name)
        await fire_broadcasts(tr)
        return "Scene VFX updated and live-reloaded"
    tools["scene_vfx"] = scene_vfx

    async def scene_vfx_data(data: dict, canvas_name: str = "") -> str:
        """Push live data to the scene VFX animation loop.

        The data is available in VFX code as `window.__vfxData`.
        Call this at high frequency (e.g. 10-30fps) from a music panel
        to drive audio-reactive visuals.

        Args:
            data: Arbitrary key-value pairs (e.g. {"bass": 0.8, "mid": 0.3, "bpm": 120}).
            canvas_name: Target canvas name. Empty = first canvas.
        """
        tr = await _scene_vfx_data(data, canvas_name=canvas_name)
        await fire_broadcasts(tr)
        return "ok"
    tools["scene_vfx_data"] = scene_vfx_data

    async def get_handbook_canvas(skill: str = "") -> str:
        """Get canvas plugin handbook.

        Without arguments: lists available canvas skills.
        With skill name: returns that specific skill doc.

        Available skills: canvas-management

        Examples:
            get_handbook_canvas()                          # list skills
            get_handbook_canvas(skill="canvas-management") # full doc
        """
        tr = await _get_handbook_canvas(skill)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return tr.data["text"]
    tools["get_handbook_canvas"] = get_handbook_canvas

    async def spatial_discovery(
        agent_id: str,
        radius: float | None = None,
    ) -> list[dict]:
        """Discover nearby agents by spatial proximity on the canvas.

        Uses edge-to-edge (raytraced) distance between agent bounding boxes.
        With radius: returns all agents within that pixel distance, sorted by proximity.
        Without radius: returns only the single closest agent.
        Only finds agents on the same canvas (same parent).

        Args:
            agent_id: The agent to search from.
            radius: Max distance in canvas pixels. None = closest only.
        """
        tr = await _spatial_discovery(agent_id, radius)
        return tr.data
    tools["spatial_discovery"] = spatial_discovery

    return tools


from core.chat_run import chat_run


@chat_run
async def run(ask, say):
    """Add a canvas and open it in the browser."""
    import webbrowser
    from core.tools._state import _engine
    from core.tools._bundles import _add_bundle

    if not _engine:
        say("no engine — start server first")
        return

    name = await ask("canvas name? (default: main)")
    name = name.strip() or "main"

    # Add canvas (on_add handles name uniqueness — skips if exists)
    tr = await _add_bundle("canvas", name=name)
    if hasattr(tr, "data") and isinstance(tr.data, dict) and "error" in tr.data:
        say(f"error: {tr.data['error']}")
        return

    # Get port from engine config
    config = _engine.store.get_config()
    port = config.get("port", 8888)
    url = f"http://localhost:{port}/canvas/{name}"
    say(url)
    webbrowser.open(url)
