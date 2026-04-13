"""Tests for terminal tool inner functions."""

from core.tools._process import (
    _agent_call,
    _process_output,
    _process_restart,
    _process_signal,
)
from core.tools._agents import _create_agent


async def test_agent_call_no_target(setup):
    tr = await _agent_call(target_agent_id="nonexistent", message="hi")
    assert "error" in tr.data


async def test_agent_call_to_existing_agent(setup):
    await _create_agent(agent_id="t1")
    tr = await _agent_call(target_agent_id="t1", message="hello")
    assert tr.data["delivered"] is True
    assert tr.data["target_agent_id"] == "t1"


async def test_terminal_output_no_process(setup):
    tr = await _process_output(agent_id="nonexistent")
    assert "error" in tr.data


async def test_terminal_restart_no_process(setup):
    tr = await _process_restart(agent_id="nonexistent")
    assert "error" in tr.data


async def test_terminal_restart_no_id(setup):
    tr = await _process_restart()
    assert "error" in tr.data


async def test_terminal_signal_no_process(setup):
    tr = await _process_signal(agent_id="nonexistent")
    assert "error" in tr.data
