"""Conftest for web-bundle tests — wires engine + a real web agent."""

import pytest
from pathlib import Path

from core.engine import Engine
from core.tools import _state


@pytest.fixture
async def engine_with_web(tmp_path: Path):
    eng = Engine(project_dir=tmp_path, broadcast=lambda msg: None)
    await eng.start()
    _state._engine = eng
    from bundled_agents.web import tools as web_tools

    web_tools._engine = eng
    # Fresh per-test cache
    web_tools._aliases_cache.clear()
    agent = eng.store.create_agent(bundle="web")
    eng.store.update_agent_meta(agent["id"], port=8888, display_name="main")
    yield eng, agent["id"], web_tools
    web_tools._aliases_cache.clear()
    await eng.stop()
    _state._engine = None
