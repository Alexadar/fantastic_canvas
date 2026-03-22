"""Shared fixtures for fantastic_agent bundle tests."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.engine import Engine
from core.tools import init_tools
from core.process_runner import ProcessRunner


class Broadcasts:
    """Collects broadcast messages."""
    def __init__(self):
        self.messages = []

    async def __call__(self, msg):
        self.messages.append(msg)

    def clear(self):
        self.messages.clear()

    def of_type(self, t):
        return [m for m in self.messages if m.get("type") == t]


def _pre_add_bundles(project_dir):
    """Simulate `fantastic add canvas` + fantastic_agent — create agents for both bundles."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    canvas = store.create_agent(bundle="canvas")
    store.update_agent_meta(canvas["id"], display_name="main", is_container=True)
    store.create_agent(bundle="fantastic_agent", parent=canvas["id"])


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    """Wire engine + process_runner + broadcast into tools.

    Monkeypatches core.server.broadcast so dispatch handlers collect
    messages into the Broadcasts instance (no real server needed).
    """
    from core.tools import _state
    _state._on_agent_created.clear()

    _pre_add_bundles(str(tmp_path))
    engine = Engine(project_dir=str(tmp_path))
    await engine.start()
    bc = Broadcasts()
    pr = ProcessRunner()
    init_tools(engine, bc, pr)

    # Patch core.server.broadcast so handlers that import it at call-time
    # route messages through our Broadcasts collector.
    import core.server as _server_mod
    monkeypatch.setattr(_server_mod, "broadcast", bc)

    yield engine, bc, pr
    await pr.close_all()
    await engine.stop()

    _state._on_agent_created.clear()
    _state._engine = None
    _state._broadcast = None
    _state._process_runner = None
