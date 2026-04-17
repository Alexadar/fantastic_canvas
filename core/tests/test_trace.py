"""Tests for core.trace — dispatch tracing via bus.on_message."""

import pytest

from core.bus import bus
from core.trace import trace


@pytest.fixture(autouse=True)
def clear_subscribers():
    bus._on_message.clear()
    yield
    bus._on_message.clear()


async def test_trace_ok_path_emits_event():
    events = []
    bus.on_message(lambda ev: events.append(ev))

    async def fn(**kwargs):
        return {"result_value": 123}

    result = await trace("ws", "canvas_main", "get_state", {}, fn)
    assert result == {"result_value": 123}
    assert len(events) == 1
    ev = events[0]
    assert ev["source"] == "ws"
    assert ev["source_agent_id"] == "canvas_main"
    assert ev["tool"] == "get_state"
    assert ev["status"] == "ok"
    assert ev["error"] is None
    assert ev["result"] == {"result_value": 123}
    assert "get_state" in ev["message"]
    assert "ok" in ev["message"]


async def test_trace_error_path_emits_and_raises():
    events = []
    bus.on_message(lambda ev: events.append(ev))

    async def failing_fn(**kwargs):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await trace("scheduler", "agent_x", "rename_agent", {"x": 1}, failing_fn)

    assert len(events) == 1
    ev = events[0]
    assert ev["status"] == "error"
    assert ev["error"] == "boom"
    assert ev["result"] is None
    assert "error" in ev["message"]


async def test_trace_no_subscribers_is_noop():
    # Verify tracing works when nobody listens (just ensures no crash)
    async def fn(**kwargs):
        return "ok"

    result = await trace("ws", None, "tool", {}, fn)
    assert result == "ok"


async def test_on_message_subscriber_error_isolated():
    """A failing subscriber must not break other subscribers or the dispatch."""
    events = []

    def bad(ev):
        raise ValueError("subscriber bug")

    bus.on_message(bad)
    bus.on_message(lambda ev: events.append(ev))

    async def fn(**kwargs):
        return 42

    result = await trace("ws", "a1", "t", {}, fn)
    assert result == 42
    assert len(events) == 1  # good subscriber still called


async def test_trace_forwards_args_verbatim():
    """Verbatim pass-through — no truncation."""
    events = []
    bus.on_message(lambda ev: events.append(ev))

    big_text = "x" * 10_000

    async def fn(**kwargs):
        return {"big": big_text}

    await trace("ws", "a1", "write_file", {"content": big_text}, fn)
    assert events[0]["args"]["content"] == big_text
    assert events[0]["result"]["big"] == big_text


async def test_unsubscribe_stops_events():
    events = []
    unsub = bus.on_message(lambda ev: events.append(ev))

    async def fn(**kwargs):
        return None

    await trace("ws", None, "t", {}, fn)
    assert len(events) == 1

    unsub()
    await trace("ws", None, "t", {}, fn)
    assert len(events) == 1  # unchanged


async def test_async_subscriber_awaited():
    calls = []

    async def async_sub(ev):
        calls.append(ev)

    bus.on_message(async_sub)

    async def fn(**kwargs):
        return None

    await trace("ws", None, "t", {}, fn)
    assert len(calls) == 1


async def test_duration_ms_present():
    events = []
    bus.on_message(lambda ev: events.append(ev))

    async def fn(**kwargs):
        import asyncio

        await asyncio.sleep(0.01)
        return None

    await trace("ws", None, "t", {}, fn)
    assert events[0]["duration_ms"] >= 10
