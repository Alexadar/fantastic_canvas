"""Dashboard bundle — read-only agent cards overview with live updates.

A self-contained HTML dashboard that shows cards for all top-level agents
(canvases, dashboards, standalone bundles). Multiple dashboard instances
are supported — each is a real agent (bundle="dashboard") with its own
display_name, served at /dashboard/{name}.

The bundle registers its own /dashboard/{name} route on the FastAPI app —
core knows nothing about dashboards.
"""

import logging
from pathlib import Path

from core.dispatch import ToolResult

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"
_BUNDLE_DIR = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

# Module-level engine ref (set in register_tools)
_engine = None


def on_add(project_dir: str, name: str = "", working_dir: str = "") -> None:
    """Called by `fantastic add dashboard` — creates a dashboard agent with the given name."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    display = name or "main"
    # Check name uniqueness among dashboard agents
    for a in store.list_agents():
        if a.get("bundle") == "dashboard" and a.get("display_name") == display:
            print(f"  Dashboard '{display}' already exists: {a['id']}")
            return
    agent = store.create_agent(bundle="dashboard")
    meta: dict = {"display_name": display}
    if working_dir:
        meta["working_dir"] = working_dir
    store.update_agent_meta(agent["id"], **meta)
    print(f"  Dashboard '{display}' created: {agent['id']}")


async def _get_handbook_dashboard(skill: str = "") -> ToolResult:
    if skill:
        skill_file = _SKILLS_DIR / f"{skill}.md"
        if skill_file.exists():
            return ToolResult(data={"text": f"# SKILL: {skill}\n\n{skill_file.read_text()}"})
        available = [p.stem for p in _SKILLS_DIR.glob("*.md")] if _SKILLS_DIR.exists() else []
        avail_str = ", ".join(sorted(available)) or "(none)"
        return ToolResult(data={"error": f"Skill '{skill}' not found. Available: {avail_str}"})
    available = sorted(p.stem for p in _SKILLS_DIR.glob("*.md")) if _SKILLS_DIR.exists() else []
    return ToolResult(data={"text": "Dashboard skills: " + ", ".join(available) if available else "No dashboard skills found."})


def register_dispatch():
    """Return inner dispatch functions for _DISPATCH table."""
    return {
        "get_handbook_dashboard": _get_handbook_dashboard,
    }


def register_tools(engine, fire_broadcasts, process_runner=None):
    """Register dashboard tools and HTTP route onto the server."""
    global _engine
    _engine = engine
    tools = {}

    # ─── Self-register /dashboard/{name} route on the FastAPI app ──
    from core.server import app
    from fastapi.responses import FileResponse
    from starlette.responses import Response

    html_path = _BUNDLE_DIR / "index.html"

    @app.get("/dashboard/{dashboard_name}")
    async def serve_dashboard(dashboard_name: str):
        """Serve the dashboard HTML page for a specific dashboard instance."""
        if not _engine:
            return Response(status_code=503, content="Engine not ready")
        found = None
        for a in _engine.store.list_agents():
            if a.get("bundle") == "dashboard" and a.get("display_name") == dashboard_name:
                found = a
                break
        if not found:
            return Response(status_code=404, content=f"Dashboard '{dashboard_name}' not found")
        if not html_path.exists():
            return Response(status_code=503, content="Dashboard HTML not found")
        return FileResponse(str(html_path), media_type="text/html")

    # ─── Log URL only if a dashboard agent exists ──
    if engine.store.find_by_bundle("dashboard"):
        config = engine.store.get_config()
        port = config.get("port", 8888)
        logger.info(f"dashboard on http://localhost:{port}")

    # ─── Tools ──

    async def get_handbook_dashboard(skill: str = "") -> str:
        """Get dashboard plugin handbook.

        Without arguments: lists available dashboard skills.
        With skill name: returns that specific skill doc.

        Available skills: dashboard-overview

        Examples:
            get_handbook_dashboard()                              # list skills
            get_handbook_dashboard(skill="dashboard-overview")    # full doc
        """
        tr = await _get_handbook_dashboard(skill)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return tr.data["text"]
    tools["get_handbook_dashboard"] = get_handbook_dashboard

    return tools
