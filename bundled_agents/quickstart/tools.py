"""Quickstart — interactive project setup wizard.

Guides first-time users through adding canvas, terminal, and AI integration.
Self-deletes after setup. Re-running detects existing config and exits.
"""

from pathlib import Path
from core.chat_run import chat_run

NAME = "quickstart"


def on_add(project_dir: str, name: str = "", working_dir: str = "") -> None:
    """Create a quickstart agent (so server starts on next `fantastic`)."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    if store.find_by_bundle("quickstart"):
        print("  Quickstart already exists")
        return
    agent = store.create_agent(bundle="quickstart")
    store.update_agent_meta(agent["id"], display_name=name or "quickstart")
    print(f"  Quickstart created: {agent['id']}")


@chat_run
async def run(ask, say):
    """Auto setup wizard. Discovered by core via @chat_run."""
    from core.tools._state import _engine
    from core.tools._bundles import _add_bundle

    if not _engine:
        say(
            "no engine available — run 'fantastic add quickstart' then 'fantastic' first"
        )
        return

    # Guard: already configured?
    agents = _engine.store.list_agents()
    non_qs = [a for a in agents if a.get("bundle") != "quickstart"]
    if non_qs:
        say("project already configured — use 'add'/'remove' to modify bundles")
        qs = _engine.store.find_by_bundle("quickstart")
        if qs:
            _engine.store.delete_agent(qs["id"])
        return

    say("Quickstart adds default web + canvas. Subject to be updated later. Enjoy!")

    # Pre-create with deterministic IDs:
    #   web_main  ─ transport root (is_container)
    #     └─ canvas_main  ─ spatial host (parent = web_main)
    # Plus file_project at the root (no parent) — filesystem access for everything.
    # Subsequent agents (terminal, ollama, etc.) auto-parent to canvas_main.
    store = _engine.store
    if not store.get_agent("web_main"):
        store.create_agent(bundle="web", agent_id="web_main")
        store.update_agent_meta(
            "web_main",
            port=8888,
            base_route="",
            display_name="main",
            is_container=True,
        )
    if not store.get_agent("canvas_main"):
        store.create_agent(bundle="canvas", agent_id="canvas_main", parent="web_main")
        store.update_agent_meta("canvas_main", display_name="main", is_container=True)
    if not store.get_agent("file_project"):
        store.create_agent(bundle="file", agent_id="file_project")
        store.update_agent_meta(
            "file_project", display_name="project", root="", readonly=False
        )
    if not store.get_agent("scheduler_main"):
        store.create_agent(bundle="scheduler", agent_id="scheduler_main")
        store.update_agent_meta(
            "scheduler_main", display_name="main", tick_sec=1.0, paused=False
        )

    # Web transport first — every UI agent needs a web agent to serve it.
    tr = await _add_bundle("web", name="main")
    if hasattr(tr, "data") and "error" in tr.data:
        say(f"  web error: {tr.data['error']}")

    tr = await _add_bundle("canvas", name="main")
    if hasattr(tr, "data") and "error" in tr.data:
        say(f"  canvas error: {tr.data['error']}")

    tr = await _add_bundle("file", name="project")
    if hasattr(tr, "data") and "error" in tr.data:
        say(f"  file error: {tr.data['error']}")

    tr = await _add_bundle("scheduler", name="main")
    if hasattr(tr, "data") and "error" in tr.data:
        say(f"  scheduler error: {tr.data['error']}")

    # Self-delete
    qs = _engine.store.find_by_bundle("quickstart")
    if qs:
        _engine.store.delete_agent(qs["id"])
