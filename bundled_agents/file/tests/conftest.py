"""Conftest for `file` bundle tests — wires engine + the bundle module."""

import pytest
from pathlib import Path

from core.engine import Engine
from core.tools import _state


@pytest.fixture
async def engine(tmp_path: Path):
    eng = Engine(project_dir=tmp_path, broadcast=lambda msg: None)
    await eng.start()
    _state._engine = eng
    from bundled_agents.file import tools as file_tools

    file_tools._engine = eng
    yield eng
    await eng.stop()
    _state._engine = None
