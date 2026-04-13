"""Tests for the on_subagents_loaded hook mechanism."""

import pytest

from core.tools import fire_subagents_loaded
from core.tools import _state as _tools_state


@pytest.fixture(autouse=True)
def clear_hooks():
    _tools_state._on_subagents_loaded.clear()
    yield
    _tools_state._on_subagents_loaded.clear()


async def test_sync_hook_fires():
    calls = []
    _tools_state._on_subagents_loaded.append(lambda engine: calls.append(engine))
    await fire_subagents_loaded("mock_engine")
    assert calls == ["mock_engine"]


async def test_async_hook_fires():
    results = []

    async def hook(engine):
        results.append(("async", engine))

    _tools_state._on_subagents_loaded.append(hook)
    await fire_subagents_loaded("engine_x")
    assert results == [("async", "engine_x")]


async def test_failing_hook_does_not_break_others():
    calls = []

    def bad(_engine):
        raise RuntimeError("boom")

    def good(engine):
        calls.append(engine)

    _tools_state._on_subagents_loaded.append(bad)
    _tools_state._on_subagents_loaded.append(good)
    await fire_subagents_loaded("e")
    assert calls == ["e"]


async def test_multiple_hooks_fire_in_order():
    order = []
    _tools_state._on_subagents_loaded.append(lambda e: order.append(1))
    _tools_state._on_subagents_loaded.append(lambda e: order.append(2))
    _tools_state._on_subagents_loaded.append(lambda e: order.append(3))
    await fire_subagents_loaded(None)
    assert order == [1, 2, 3]
