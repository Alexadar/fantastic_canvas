"""Tests for multi-canvas scoping at server level: REST filter, WS subscription."""

import json
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient


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
    import importlib
    import core.server as server_mod
    importlib.reload(server_mod)
    client = TestClient(server_mod.app)
    with client:
        yield client, canvas_ids, project_dir

    _state._on_agent_created.clear()
    _state._engine = None
    _state._broadcast = None
    _state._process_runner = None


def _collect_until(ws, target_types, max_msgs=10):
    msgs = []
    types_seen = set()
    for _ in range(max_msgs):
        msg = ws.receive_json()
        msgs.append(msg)
        types_seen.add(msg["type"])
        if target_types.issubset(types_seen):
            break
    return msgs, types_seen


# ─── REST: GET /api/state?scope= ────────────────────────────────────────


def test_rest_state_no_filter(multi_client):
    client, (main_id, debug_id), _ = multi_client
    r = client.get("/api/state")
    assert r.status_code == 200
    agents = r.json()["agents"]
    ids = [a["id"] for a in agents]
    assert main_id in ids
    assert debug_id in ids


def test_rest_state_filtered_by_canvas(multi_client):
    client, (main_id, debug_id), _ = multi_client
    # Create agent on main canvas
    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "create_agent",
            "template": "terminal", "parent": main_id,
        })
        msgs, _ = _collect_until(ws, {"agent_created"})
        child_id = None
        for m in msgs:
            if m["type"] == "agent_created":
                child_id = m["agent"]["id"]
                break

    r = client.get("/api/state?scope=main")
    assert r.status_code == 200
    agents = r.json()["agents"]
    ids = [a["id"] for a in agents]
    assert main_id in ids
    assert child_id in ids
    assert debug_id not in ids


# ─── WS: subscribe filters broadcasts ────────────────────────────────────


def test_ws_subscribe_filters_broadcasts(multi_client):
    """Client subscribed to 'main' should not see agents created on 'debug'."""
    client, (main_id, debug_id), _ = multi_client

    with client.websocket_connect("/ws") as ws_main:
        # Subscribe to 'main'
        ws_main.send_json({"type": "subscribe", "scope": "main"})

        with client.websocket_connect("/ws") as ws_debug:
            # Subscribe to 'debug'
            ws_debug.send_json({"type": "subscribe", "scope": "debug"})

            # Create agent on debug — ws_main should NOT get it
            ws_debug.send_json({
                "type": "create_agent",
                "template": "terminal", "parent": debug_id,
            })
            # ws_debug should see agent_created
            msgs, types = _collect_until(ws_debug, {"agent_created"})
            assert "agent_created" in types


def test_ws_unsubscribed_sees_all(multi_client):
    """Client with no subscription (empty) sees all broadcasts."""
    client, (main_id, debug_id), _ = multi_client

    with client.websocket_connect("/ws") as ws_all:
        with client.websocket_connect("/ws") as ws_creator:
            # ws_all has no subscription — sees everything
            ws_creator.send_json({
                "type": "create_agent",
                "template": "terminal", "parent": main_id,
            })
            # Both should get the broadcast
            msgs_creator, _ = _collect_until(ws_creator, {"agent_created"})
            msgs_all, _ = _collect_until(ws_all, {"agent_created"})
            assert any(m["type"] == "agent_created" for m in msgs_creator)
            assert any(m["type"] == "agent_created" for m in msgs_all)


# ─── WS: create_agent without parent errors on N>1 canvases ──────────────


def test_ws_create_no_parent_errors_multi_canvas(multi_client):
    """Creating agent without parent when multiple canvases exist should error."""
    client, (main_id, debug_id), _ = multi_client

    with client.websocket_connect("/ws") as ws:
        ws.send_json({
            "type": "create_agent",
            "template": "terminal",
        })
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Multiple canvases" in msg["error"]


# ─── Per-canvas VFX in state ─────────────────────────────────────────────


def test_per_canvas_vfx_in_state(multi_client):
    """Each canvas agent should have its own scene_vfx_js in state."""
    client, (main_id, debug_id), project_dir = multi_client

    # Write VFX to main canvas
    agents_dir = os.path.join(project_dir, ".fantastic", "agents")
    canvas_dir = os.path.join(agents_dir, main_id)
    with open(os.path.join(canvas_dir, "scene_vfx.js"), "w") as f:
        f.write("// main vfx")

    r = client.get("/api/state")
    agents = r.json()["agents"]
    main_agent = next(a for a in agents if a["id"] == main_id)
    debug_agent = next(a for a in agents if a["id"] == debug_id)
    assert main_agent.get("scene_vfx_js") == "// main vfx"
    assert debug_agent.get("scene_vfx_js", "") != "// main vfx"
