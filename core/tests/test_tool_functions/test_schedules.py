"""Tests for schedule tools — create, list, delete."""

from core.tools._schedules import _create_schedule, _list_schedules, _delete_schedule
from core.tools._agents import _create_agent


async def test_create_schedule(setup):
    engine, _, _ = setup
    await _create_agent(agent_id="sa1")
    tr = await _create_schedule(
        agent_id="sa1",
        action={"type": "tool", "tool": "get_state", "args": {}},
        interval_seconds=120,
    )
    assert "schedule" in tr.data
    assert tr.data["schedule"]["interval_seconds"] == 120


async def test_create_schedule_no_agent_id(setup):
    tr = await _create_schedule(agent_id="", action={"type": "tool", "tool": "x"})
    assert "error" in tr.data


async def test_create_schedule_bad_action(setup):
    tr = await _create_schedule(agent_id="sa1", action={"type": "invalid"})
    assert "error" in tr.data


async def test_create_schedule_prompt(setup):
    await _create_agent(agent_id="sa2")
    tr = await _create_schedule(
        agent_id="sa2",
        action={"type": "prompt", "text": "check logs"},
        interval_seconds=60,
    )
    assert tr.data["schedule"]["action"]["type"] == "prompt"


async def test_list_schedules(setup):
    await _create_agent(agent_id="sl1")
    await _create_schedule(
        agent_id="sl1",
        action={"type": "tool", "tool": "get_state"},
        interval_seconds=30,
    )
    tr = await _list_schedules(agent_id="sl1")
    assert len(tr.data["schedules"]) == 1


async def test_list_schedules_empty(setup):
    await _create_agent(agent_id="sl2")
    tr = await _list_schedules(agent_id="sl2")
    assert tr.data["schedules"] == []


async def test_delete_schedule(setup):
    await _create_agent(agent_id="sd1")
    tr = await _create_schedule(
        agent_id="sd1",
        action={"type": "tool", "tool": "get_state"},
        interval_seconds=30,
    )
    sch_id = tr.data["schedule"]["id"]
    tr = await _delete_schedule(agent_id="sd1", schedule_id=sch_id)
    assert tr.data["deleted"] is True
    # Verify gone
    tr = await _list_schedules(agent_id="sd1")
    assert tr.data["schedules"] == []


async def test_delete_schedule_not_found(setup):
    await _create_agent(agent_id="sd2")
    tr = await _delete_schedule(agent_id="sd2", schedule_id="sch_nonexistent")
    assert "error" in tr.data
