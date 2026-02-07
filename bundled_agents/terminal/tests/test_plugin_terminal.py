"""Tests for terminal bundle plugin wrappers (tool-level functions)."""

import pytest

from core.tools import _TOOL_DISPATCH


async def test_terminal_output_error(setup):
    """terminal_output with no process → [ERROR] string."""
    result = await _TOOL_DISPATCH["terminal_output"](agent_id="nonexistent")
    assert isinstance(result, str)
    assert "[ERROR]" in result


async def test_terminal_restart_error(setup):
    """terminal_restart with no process → [ERROR] string."""
    result = await _TOOL_DISPATCH["terminal_restart"](agent_id="nonexistent")
    assert isinstance(result, str)
    assert "[ERROR]" in result


async def test_terminal_signal_error(setup):
    """terminal_signal with no process → [ERROR] string."""
    result = await _TOOL_DISPATCH["terminal_signal"](agent_id="nonexistent")
    assert isinstance(result, str)
    assert "[ERROR]" in result
