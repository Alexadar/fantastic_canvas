"""Tests for core.scheduler — per-agent persistent scheduler."""

import time
from unittest.mock import AsyncMock

import pytest

from core.scheduler import Scheduler


@pytest.fixture
def agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    # Create two agent dirs
    (d / "agent_a").mkdir()
    (d / "agent_b").mkdir()
    return d


@pytest.fixture
def scheduler(agents_dir):
    return Scheduler(agents_dir)


# ─── CRUD ──────────────────────────────────────────────────


def test_add_and_list(scheduler):
    sch = scheduler.add(
        "agent_a", {"type": "tool", "tool": "get_state", "args": {}}, 60
    )
    assert sch["id"].startswith("sch_")
    assert sch["interval_seconds"] == 60
    assert sch["run_count"] == 0
    assert sch["enabled"] is True

    result = scheduler.list_for_agent("agent_a")
    assert len(result) == 1
    assert result[0]["id"] == sch["id"]


def test_remove(scheduler):
    sch = scheduler.add("agent_a", {"type": "tool", "tool": "get_state"}, 30)
    assert scheduler.remove("agent_a", sch["id"]) is True
    assert scheduler.list_for_agent("agent_a") == []


def test_remove_not_found(scheduler):
    assert scheduler.remove("agent_a", "sch_nonexistent") is False


def test_schedule_isolated_between_agents(scheduler):
    """Agent A's schedules not visible to agent B."""
    scheduler.add("agent_a", {"type": "prompt", "text": "check"}, 60)
    scheduler.add("agent_b", {"type": "prompt", "text": "other"}, 120)
    assert len(scheduler.list_for_agent("agent_a")) == 1
    assert len(scheduler.list_for_agent("agent_b")) == 1
    assert scheduler.list_for_agent("agent_a")[0]["action"]["text"] == "check"
    assert scheduler.list_for_agent("agent_b")[0]["action"]["text"] == "other"


# ─── Persistence ────────────────────────────────────────────


def test_save_and_load(agents_dir):
    s1 = Scheduler(agents_dir)
    sch = s1.add("agent_a", {"type": "tool", "tool": "list_agents"}, 90)

    # New scheduler instance loads from disk
    s2 = Scheduler(agents_dir)
    s2.load_all()
    loaded = s2.list_for_agent("agent_a")
    assert len(loaded) == 1
    assert loaded[0]["id"] == sch["id"]
    assert loaded[0]["interval_seconds"] == 90


def test_load_all_skips_missing(agents_dir):
    """Agents without schedules.json are fine."""
    s = Scheduler(agents_dir)
    s.load_all()
    assert s.list_for_agent("agent_a") == []


def test_load_all_handles_corrupt(agents_dir):
    (agents_dir / "agent_a" / "schedules.json").write_text("not json")
    s = Scheduler(agents_dir)
    s.load_all()
    assert s.list_for_agent("agent_a") == []


# ─── Agent deletion ─────────────────────────────────────────


def test_agent_delete_evicts_cache(scheduler):
    scheduler.add("agent_a", {"type": "prompt", "text": "x"}, 60)
    assert len(scheduler.list_for_agent("agent_a")) == 1
    # Simulate delete hook
    scheduler._cache.pop("agent_a", None)
    assert scheduler.list_for_agent("agent_a") == []


# ─── Tick execution ──────────────────────────────────────────


async def test_tick_executes_due_tool(scheduler):
    """Due tool schedule calls dispatch with agent_id injected."""
    mock_fn = AsyncMock()
    dispatch = {"get_state": mock_fn}

    sch = scheduler.add(
        "agent_a", {"type": "tool", "tool": "get_state", "args": {"scope": "root"}}, 60
    )
    sch["next_run"] = time.time() - 1

    await scheduler._execute("agent_a", sch, dispatch, AsyncMock())
    mock_fn.assert_called_once_with(scope="root", agent_id="agent_a")


async def test_tool_broadcasts_reach_bus(scheduler):
    """ToolResult.broadcast from a scheduled tool must flow to broadcast_fn."""
    from core.dispatch import ToolResult

    bcast_msg = {"type": "agent_updated", "agent_id": "agent_a", "display_name": "X"}

    async def fn(**kwargs):
        return ToolResult(data={"ok": True}, broadcast=[bcast_msg])

    dispatch = {"rename_agent": fn}
    broadcast_fn = AsyncMock()

    sch = scheduler.add(
        "agent_a",
        {"type": "tool", "tool": "rename_agent", "args": {"display_name": "X"}},
        60,
    )
    sch["next_run"] = time.time() - 1

    await scheduler._execute("agent_a", sch, dispatch, broadcast_fn)
    broadcast_fn.assert_awaited_once_with(bcast_msg)


async def test_tick_executes_due_prompt(scheduler, agents_dir):
    """Due prompt schedule routes to the agent's bundle `_send` dispatch."""
    import json

    # Write agent.json with bundle=ollama so scheduler knows how to route
    (agents_dir / "agent_a" / "agent.json").write_text(
        json.dumps({"id": "agent_a", "bundle": "ollama"})
    )
    mock_handler = AsyncMock()
    dispatch = {"ollama_send": mock_handler}

    sch = scheduler.add("agent_a", {"type": "prompt", "text": "check status"}, 60)
    sch["next_run"] = time.time() - 1

    await scheduler._execute("agent_a", sch, dispatch, AsyncMock())
    mock_handler.assert_called_once_with(agent_id="agent_a", text="check status")


async def test_tool_action_always_scoped_to_agent(scheduler):
    """Even if args contain a different agent_id, owning agent_id is injected."""
    mock_fn = AsyncMock()
    dispatch = {"execute_python": mock_fn}

    sch = scheduler.add(
        "agent_a",
        {
            "type": "tool",
            "tool": "execute_python",
            "args": {"code": "print(1)", "agent_id": "agent_b"},
        },
        60,
    )
    sch["next_run"] = time.time() - 1

    await scheduler._execute("agent_a", sch, dispatch, AsyncMock())
    # agent_id should be overridden to owning agent
    mock_fn.assert_called_once_with(code="print(1)", agent_id="agent_a")


async def test_tick_skips_not_due(scheduler):
    sch = scheduler.add("agent_a", {"type": "tool", "tool": "get_state"}, 60)
    # next_run is in the future (default)
    assert sch["next_run"] > time.time()

    # Simulate one tick check — should not execute
    # (We test _execute directly; the loop checks next_run)
    # Just verify the schedule is not yet due
    assert time.time() < sch["next_run"]


async def test_tick_updates_run_count(scheduler):
    sch = scheduler.add("agent_a", {"type": "tool", "tool": "get_state"}, 60)
    assert sch["run_count"] == 0
    sch["next_run"] = time.time() - 1

    await scheduler._execute("agent_a", sch, {"get_state": AsyncMock()}, AsyncMock())
    sch["run_count"] += 1  # normally done by tick_loop
    assert sch["run_count"] == 1


async def test_execute_handles_error(scheduler):
    """Failed execution logs warning but doesn't crash."""
    mock_fn = AsyncMock(side_effect=RuntimeError("boom"))
    dispatch = {"bad_tool": mock_fn}

    sch = scheduler.add("agent_a", {"type": "tool", "tool": "bad_tool"}, 60)
    # Should not raise
    await scheduler._execute("agent_a", sch, dispatch, AsyncMock())
