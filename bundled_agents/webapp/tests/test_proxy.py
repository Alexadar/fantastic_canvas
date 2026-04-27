"""webapp/_proxy.py — WS frame protocol."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from webapp.app import make_app


@pytest.fixture
def client(seeded_kernel):
    app = make_app("test_web", seeded_kernel)
    with TestClient(app) as c:
        yield c


def _read_until_reply(ws, call_id, max_frames=10):
    """Drain frames from ws until the reply for `call_id` arrives. Auto-watch
    of the host agent may send `event` frames before the reply lands."""
    for _ in range(max_frames):
        msg = json.loads(ws.receive_text())
        if msg.get("type") == "reply" and msg.get("id") == call_id:
            return msg
    raise AssertionError(f"no reply for id={call_id} within {max_frames} frames")


def test_ws_call_returns_reply(client, seeded_kernel):
    with client.websocket_connect("/core/ws") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "call",
                    "target": "core",
                    "payload": {"type": "reflect"},
                    "id": "1",
                }
            )
        )
        msg = _read_until_reply(ws, "1")
        assert "verbs" in msg["data"]


def test_ws_emit_no_reply(client, seeded_kernel):
    with client.websocket_connect("/core/ws") as ws:
        ws.send_text(
            json.dumps(
                {"type": "emit", "target": "core", "payload": {"type": "marker"}}
            )
        )
        # No reply expected; just verify connection still alive via a follow-up call
        ws.send_text(
            json.dumps(
                {
                    "type": "call",
                    "target": "core",
                    "payload": {"type": "reflect"},
                    "id": "x",
                }
            )
        )
        msg = _read_until_reply(ws, "x")
        assert msg["type"] == "reply"


def test_ws_watch_routes_events(client, seeded_kernel):
    with client.websocket_connect("/core/ws") as ws:
        ws.send_text(json.dumps({"type": "watch", "src": "core"}))
        ws.send_text(
            json.dumps(
                {
                    "type": "call",
                    "target": "core",
                    "payload": {"type": "reflect"},
                    "id": "1",
                }
            )
        )
        msg = _read_until_reply(ws, "1")
        assert msg["data"] is not None
