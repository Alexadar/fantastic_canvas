"""Tests for multi-canvas scoping: parent filter, canvas filter, auto-parent error."""

import pytest

from core.tools._agents import (
    _create_agent,
    _list_agents,
    _get_full_state,
)
from core.dispatch import ToolResult
from core.engine import Engine
from core.tools import init_tools
from core.process_runner import ProcessRunner


class Broadcasts:
    def __init__(self):
        self.messages = []

    async def __call__(self, msg):
        self.messages.append(msg)

    def clear(self):
        self.messages.clear()

    def of_type(self, t):
        return [m for m in self.messages if m.get("type") == t]


def _pre_add_two_canvases(project_dir):
    """Create two canvas agents: 'main' and 'debug'."""
    from core.agent_store import AgentStore
    from pathlib import Path

    store = AgentStore(Path(project_dir))
    store.init()
    c1 = store.create_agent(bundle="canvas")
    store.update_agent_meta(c1["id"], display_name="main", is_container=True)
    c2 = store.create_agent(bundle="canvas")
    store.update_agent_meta(c2["id"], display_name="debug", is_container=True)
    return c1["id"], c2["id"]


@pytest.fixture
async def multi_setup(tmp_path):
    """Setup with two canvases."""
    from core.tools import _state
    _state._on_agent_created.clear()

    canvas_main_id, canvas_debug_id = _pre_add_two_canvases(str(tmp_path))
    engine = Engine(project_dir=str(tmp_path))
    await engine.start()
    bc = Broadcasts()
    pr = ProcessRunner()
    init_tools(engine, bc, pr)
    yield engine, bc, pr, canvas_main_id, canvas_debug_id
    await pr.close_all()
    await engine.stop()

    _state._on_agent_created.clear()
    _state._engine = None
    _state._broadcast = None
    _state._process_runner = None


# ─── list_agents with parent filter ──────────────────────────────────────


async def test_list_agents_no_filter(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    await _create_agent(parent=main_id)
    await _create_agent(parent=debug_id)
    tr = await _list_agents()
    # Should include canvases + both children
    assert len(tr.data) >= 4


async def test_list_agents_parent_filter(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    await _create_agent(agent_id="m1", parent=main_id)
    await _create_agent(agent_id="d1", parent=debug_id)
    tr = await _list_agents(parent=main_id)
    ids = [a["agent_id"] for a in tr.data]
    assert "m1" in ids
    assert "d1" not in ids
    # Canvas agents have no parent, so they're excluded too
    assert main_id not in ids
    assert debug_id not in ids


async def test_list_agents_parent_filter_empty_result(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    tr = await _list_agents(parent="nonexistent")
    assert tr.data == []


# ─── get_canvas_state with canvas filter ─────────────────────────────────


async def test_get_canvas_state_no_filter(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    await _create_agent(parent=main_id)
    await _create_agent(parent=debug_id)
    tr = await _get_full_state()
    agents = tr.data["agents"]
    assert len(agents) >= 4


async def test_get_canvas_state_filtered_by_name(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    await _create_agent(agent_id="m2", parent=main_id)
    await _create_agent(agent_id="d2", parent=debug_id)
    tr = await _get_full_state(scope="main")
    agents = tr.data["agents"]
    ids = [a["id"] for a in agents]
    assert main_id in ids
    assert "m2" in ids
    assert debug_id not in ids
    assert "d2" not in ids


async def test_get_canvas_state_unknown_canvas_returns_all(multi_setup):
    """Unknown canvas name returns full state (no match to filter on)."""
    engine, bc, pr, main_id, debug_id = multi_setup
    await _create_agent(parent=main_id)
    tr = await _get_full_state(scope="nonexistent")
    agents = tr.data["agents"]
    # No canvas with that name, so no filtering applied
    assert len(agents) >= 3


# ─── auto-parent raises on multiple canvases ─────────────────────────────


async def test_create_agent_no_parent_raises_with_multiple_canvases(multi_setup):
    """Creating without parent when N>1 canvases should raise ValueError."""
    with pytest.raises(ValueError, match="Multiple canvases exist"):
        await _create_agent()


async def test_create_agent_with_explicit_parent_succeeds(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    tr = await _create_agent(parent=main_id)
    assert tr.data["parent"] == main_id


# ─── per-canvas VFX enrichment ───────────────────────────────────────────


async def test_per_canvas_vfx_enrichment(multi_setup):
    engine, bc, pr, main_id, debug_id = multi_setup
    # Write VFX to main canvas only
    canvas_dir = engine.store.agents_dir / main_id
    (canvas_dir / "scene_vfx.js").write_text("// main vfx", encoding="utf-8")
    tr = await _get_full_state()
    agents = tr.data["agents"]
    main_agent = next(a for a in agents if a["id"] == main_id)
    assert main_agent.get("scene_vfx_js") == "// main vfx"
    # Debug canvas gets default VFX (if bundled default exists) or none
    debug_agent = next(a for a in agents if a["id"] == debug_id)
    # Either has default VFX or no VFX at all — just check it's not main's
    assert debug_agent.get("scene_vfx_js", "") != "// main vfx"
    # Top-level backward compat should still be present
    assert "scene_vfx_js" in tr.data
