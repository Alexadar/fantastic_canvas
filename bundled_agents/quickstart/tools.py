"""Quickstart — interactive project setup wizard.

Guides first-time users through adding canvas, terminal, and AI integration.
Self-deletes after setup. Re-running detects existing config and exits.
"""

from pathlib import Path
from core.chat_run import chat_run


def on_add(project_dir: str, name: str = "", working_dir: str = "") -> None:
    """Create a quickstart agent (so server starts on next `fantastic`)."""
    from core.agent_store import AgentStore
    store = AgentStore(Path(project_dir))
    store.init()
    if store.find_by_bundle("quickstart"):
        print(f"  Quickstart already exists")
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
        say("no engine available — run 'fantastic add quickstart' then 'fantastic' first")
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

    say("Quickstart adds default canvas. Subject to be updated later. Enjoy!")

    tr = await _add_bundle("canvas", name="main")
    if hasattr(tr, "data") and "error" in tr.data:
        say(f"  error: {tr.data['error']}")

    # Self-delete
    qs = _engine.store.find_by_bundle("quickstart")
    if qs:
        _engine.store.delete_agent(qs["id"])
