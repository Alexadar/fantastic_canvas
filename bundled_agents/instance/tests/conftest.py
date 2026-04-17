"""Conftest for `instance` bundle tests — wires engine + registers verb handlers."""

import pytest
from pathlib import Path

from core.engine import Engine
from core.tools import _state


@pytest.fixture
async def engine(tmp_path: Path):
    eng = Engine(project_dir=tmp_path, broadcast=lambda msg: None)
    await eng.start()
    _state._engine = eng
    # Import the bundle and wire it.
    from bundled_agents.instance import tools as inst_tools

    inst_tools._engine = eng
    yield eng
    await eng.stop()
    _state._engine = None
