"""Tests for scheduler bundle — verbs, tick loop, bus emit, history."""

import asyncio

import pytest

from bundled_agents.scheduler import tools as sched
from core.bus import bus
from core.dispatch import ToolResult, _DISPATCH


# ─── verb surface ──────────────────────────────────────────────


async def test_schedule_adds_and_returns_id(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")
    tr = await sched._schedule(
        agent_id=sid,
        for_agent_id=target["id"],
        action={"type": "tool", "tool": "noop"},
        interval_seconds=60,
    )
    assert tr.data["schedule_id"].startswith("sch_")
    assert len(sched._load_schedules(sid)) == 1


async def test_schedule_rejects_bad_action(engine_with_scheduler):
    _, sid, _ = engine_with_scheduler
    for bad in [
        {},  # no type
        {"type": "weird"},  # unknown type
        {"type": "tool"},  # missing tool
        {"type": "prompt"},  # missing text
    ]:
        tr = await sched._schedule(
            agent_id=sid, for_agent_id="x", action=bad, interval_seconds=60
        )
        assert "error" in tr.data


async def test_schedule_requires_scheduler_agent(engine_with_scheduler):
    eng, _, _ = engine_with_scheduler
    non_sched = eng.store.create_agent(bundle="terminal")
    tr = await sched._schedule(
        agent_id=non_sched["id"],
        for_agent_id="x",
        action={"type": "tool", "tool": "x"},
    )
    assert "not a scheduler agent" in tr.data["error"]


async def test_list_unschedule(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")
    add = await sched._schedule(
        agent_id=sid,
        for_agent_id=target["id"],
        action={"type": "tool", "tool": "x"},
        interval_seconds=10,
    )
    schid = add.data["schedule_id"]
    lst = await sched._list(agent_id=sid)
    assert [s["id"] for s in lst.data["schedules"]] == [schid]
    rem = await sched._unschedule(agent_id=sid, schedule_id=schid)
    assert rem.data["removed"] is True
    lst2 = await sched._list(agent_id=sid)
    assert lst2.data["schedules"] == []
    # Idempotent second removal.
    rem2 = await sched._unschedule(agent_id=sid, schedule_id=schid)
    assert rem2.data["removed"] is False


async def test_pause_and_resume_one(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")
    add = await sched._schedule(
        agent_id=sid,
        for_agent_id=target["id"],
        action={"type": "tool", "tool": "x"},
        interval_seconds=5,
    )
    schid = add.data["schedule_id"]
    await sched._pause(agent_id=sid, schedule_id=schid)
    assert sched._load_schedules(sid)[0]["paused"] is True
    await sched._resume(agent_id=sid, schedule_id=schid)
    assert sched._load_schedules(sid)[0]["paused"] is False


async def test_pause_all_scheduler_level(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    await sched._pause(agent_id=sid)  # no schedule_id → pause the whole scheduler
    assert eng.get_agent(sid)["paused"] is True
    await sched._resume(agent_id=sid)
    assert eng.get_agent(sid)["paused"] is False


# ─── fire path: tool action, bus emit, history ────────────────


async def test_tick_now_fires_tool_action(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")
    calls = []

    async def fake_tool(agent_id: str = "", **kw):
        calls.append({"agent_id": agent_id, **kw})
        return ToolResult(data={"ok": True, "value": 42})

    _DISPATCH["fake_tool_for_test"] = fake_tool
    try:
        add = await sched._schedule(
            agent_id=sid,
            for_agent_id=target["id"],
            action={"type": "tool", "tool": "fake_tool_for_test", "args": {"extra": 1}},
            interval_seconds=60,
        )
        schid = add.data["schedule_id"]
        fired = await sched._tick_now(agent_id=sid, schedule_id=schid)
        assert fired.data["fired"] is True
        assert calls == [{"agent_id": target["id"], "extra": 1}]
    finally:
        _DISPATCH.pop("fake_tool_for_test", None)


async def test_fire_emits_schedule_fired_on_both_inboxes(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")

    async def fake_tool(agent_id: str = "", **kw):
        return ToolResult(data={"ok": True})

    _DISPATCH["fake_tool_emit"] = fake_tool
    try:
        add = await sched._schedule(
            agent_id=sid,
            for_agent_id=target["id"],
            action={"type": "tool", "tool": "fake_tool_emit"},
            interval_seconds=60,
        )
        schid = add.data["schedule_id"]

        sched_msgs: list[dict] = []
        target_msgs: list[dict] = []

        async def drain(agent_id: str, bucket: list) -> None:
            try:
                async for m in bus.recv(agent_id):
                    bucket.append(m)
            except asyncio.CancelledError:
                return

        t1 = asyncio.create_task(drain(sid, sched_msgs))
        t2 = asyncio.create_task(drain(target["id"], target_msgs))
        await asyncio.sleep(0)  # let observers register

        await sched._tick_now(agent_id=sid, schedule_id=schid)
        # Give the emits a moment to hit the inboxes
        for _ in range(20):
            await asyncio.sleep(0.02)
            if sched_msgs and target_msgs:
                break
        t1.cancel()
        t2.cancel()
        for t in (t1, t2):
            try:
                await t
            except BaseException:
                pass

        assert any(m.get("event") == "schedule_fired" for m in sched_msgs)
        assert any(m.get("event") == "schedule_fired" for m in target_msgs)
    finally:
        _DISPATCH.pop("fake_tool_emit", None)


async def test_history_appended_and_read(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")

    async def fake_tool(agent_id: str = "", **kw):
        return ToolResult(data={"run": True})

    _DISPATCH["fake_hist"] = fake_tool
    try:
        add = await sched._schedule(
            agent_id=sid,
            for_agent_id=target["id"],
            action={"type": "tool", "tool": "fake_hist"},
            interval_seconds=60,
        )
        schid = add.data["schedule_id"]
        await sched._tick_now(agent_id=sid, schedule_id=schid)
        await sched._tick_now(agent_id=sid, schedule_id=schid)
    finally:
        _DISPATCH.pop("fake_hist", None)

    tr = await sched._history(agent_id=sid)
    assert tr.data["count"] == 2
    assert all(e["schedule_id"] == schid for e in tr.data["history"])

    # Filter by schedule_id.
    tr_other = await sched._history(agent_id=sid, schedule_id="sch_nope")
    assert tr_other.data["count"] == 0


async def test_history_captures_error(engine_with_scheduler):
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")
    # Schedule a tool that doesn't exist in _DISPATCH.
    add = await sched._schedule(
        agent_id=sid,
        for_agent_id=target["id"],
        action={"type": "tool", "tool": "definitely_not_registered"},
        interval_seconds=60,
    )
    await sched._tick_now(agent_id=sid, schedule_id=add.data["schedule_id"])
    hist = await sched._history(agent_id=sid)
    assert hist.data["count"] == 1
    assert "not in dispatch" in hist.data["history"][0]["error"]


# ─── tick loop end-to-end ─────────────────────────────────────


async def test_tick_loop_fires_due_schedule(engine_with_scheduler):
    """Start the real tick loop with tick_sec=0.05 and a 0.1s interval."""
    eng, sid, _ = engine_with_scheduler
    target = eng.store.create_agent(bundle="terminal")
    calls = []

    async def fake(agent_id: str = "", **kw):
        calls.append(agent_id)
        return ToolResult(data={"ok": True})

    _DISPATCH["fake_tick"] = fake
    try:
        add = await sched._schedule(
            agent_id=sid,
            for_agent_id=target["id"],
            action={"type": "tool", "tool": "fake_tick"},
            interval_seconds=1,
        )
        # Force-schedule to be due immediately.
        schs = sched._load_schedules(sid)
        schs[0]["next_run"] = 0
        sched._save_schedules(sid)

        task = asyncio.create_task(sched._tick_loop(sid))
        for _ in range(40):
            await asyncio.sleep(0.05)
            if calls:
                break
        task.cancel()
        try:
            await task
        except BaseException:
            pass
        assert calls  # the tick loop fired at least once
        _ = add  # silence unused
    finally:
        _DISPATCH.pop("fake_tick", None)


# ─── on_add ──────────────────────────────────────────────────


async def test_on_add_idempotent(engine_with_scheduler, tmp_path):
    eng, _, _ = engine_with_scheduler
    await sched.on_add(str(tmp_path), name="heartbeat")
    await sched.on_add(str(tmp_path), name="heartbeat")
    extras = [
        a for a in eng.store.list_agents() if a.get("display_name") == "heartbeat"
    ]
    assert len(extras) == 1


@pytest.fixture(autouse=True)
def _isolate_dispatch_keys():
    """Snapshot _DISPATCH keys; restore after test so stray registrations
    from broken test paths don't leak into neighbouring tests."""
    before = set(_DISPATCH.keys())
    yield
    for k in set(_DISPATCH.keys()) - before:
        _DISPATCH.pop(k, None)
