"""Conftest for scheduler-bundle tests — wires engine + a live scheduler agent."""

import pytest
from pathlib import Path

from core.engine import Engine
from core.tools import _state


@pytest.fixture
async def engine_with_scheduler(tmp_path: Path):
    eng = Engine(project_dir=tmp_path, broadcast=lambda msg: None)
    await eng.start()
    _state._engine = eng
    from bundled_agents.scheduler import tools as sched_tools

    sched_tools._engine = eng
    sched_tools._schedules_cache.clear()
    agent = eng.store.create_agent(bundle="scheduler")
    eng.store.update_agent_meta(
        agent["id"], display_name="main", tick_sec=0.05, paused=False
    )
    yield eng, agent["id"], sched_tools
    sched_tools._schedules_cache.clear()
    # Cancel any tick task that may have been spawned.
    t = sched_tools._tick_tasks.pop(agent["id"], None)
    if t and not t.done():
        t.cancel()
        try:
            await t
        except BaseException:
            pass
    await eng.stop()
    _state._engine = None
