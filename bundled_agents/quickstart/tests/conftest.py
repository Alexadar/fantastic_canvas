"""Shared fixtures for quickstart bundle tests."""

from pathlib import Path

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
    """Simulate `fantastic add canvas` + terminal agent — create agents for both bundles."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    canvas = store.create_agent(bundle="canvas")
    store.update_agent_meta(canvas["id"], display_name="main", is_container=True)
    store.create_agent(bundle="terminal", parent=canvas["id"])


@pytest.fixture
async def setup(tmp_path):
    """Wire engine + process_runner + broadcast into tools."""
    from core.tools import _state
    _state._on_agent_created.clear()

    _pre_add_bundles(str(tmp_path))
    engine = Engine(project_dir=str(tmp_path))
    await engine.start()
    bc = Broadcasts()
    pr = ProcessRunner()
    init_tools(engine, bc, pr)
    yield engine, bc, pr
    await pr.close_all()
    await engine.stop()

    _state._on_agent_created.clear()
    _state._engine = None
    _state._broadcast = None
    _state._process_runner = None
