"""Shared fixtures for canvas bundle tests."""

import importlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

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
    # Terminal agent so terminal bundle loads too
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


# ─── Server-level fixtures ────────────────────────────────────────────────


def _pre_add_two_canvases(project_dir):
    """Create two canvas agents: 'main' and 'debug'."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    c1 = store.create_agent(bundle="canvas")
    store.update_agent_meta(c1["id"], display_name="main", is_container=True)
    c2 = store.create_agent(bundle="canvas")
    store.update_agent_meta(c2["id"], display_name="debug", is_container=True)
    return c1["id"], c2["id"]


@pytest.fixture
def multi_client(tmp_path, monkeypatch):
    """TestClient with two canvases."""
    from core.tools import _state
    _state._on_agent_created.clear()

    project_dir = str(tmp_path)
    canvas_ids = _pre_add_two_canvases(project_dir)
    monkeypatch.setenv("PROJECT_DIR", project_dir)
    import core.server as server_mod
    importlib.reload(server_mod)
    client = TestClient(server_mod.app)
    with client:
        yield client, canvas_ids, project_dir

    _state._on_agent_created.clear()
    _state._engine = None
    _state._broadcast = None
    _state._process_runner = None


def _create_agent(client, template="terminal", **extra):
    """Helper: create an agent via WS and return the created agent dict."""
    with client.websocket_connect("/ws") as ws:
        msg = {
            "type": "create_agent",
            "template": template,
            **extra,
        }
        ws.send_json(msg)
        for _ in range(10):
            resp = ws.receive_json()
            if resp["type"] == "agent_created":
                return resp["agent"]
        raise RuntimeError("Did not receive agent_created message")
