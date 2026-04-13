"""Tests for agent_call dispatch — PTY delivery and AI bundle routing."""

from unittest.mock import AsyncMock, patch

from core.tools._process import _agent_call
from core.tools._agents import _create_agent


async def test_agent_call_not_found(setup):
    tr = await _agent_call(target_agent_id="nonexistent", message="hi")
    assert "error" in tr.data


async def test_agent_call_terminal_no_process(setup):
    """Terminal agent without a running process — delivered but not to process."""
    await _create_agent(agent_id="t1", template="terminal")
    tr = await _agent_call(target_agent_id="t1", message="hello")
    assert tr.data["delivered"] is True
    assert tr.data["delivered_to_process"] is False
    assert tr.data["delivered_to_chat"] is False


async def test_agent_call_ollama_routes_to_send(setup):
    """agent_call to ollama routes through ollama_send handler."""
    await _create_agent(agent_id="oll1", template="ollama")

    mock_handler = AsyncMock(return_value=None)
    with patch.dict(
        "core.dispatch._DISPATCH",
        {"ollama_send": mock_handler},
    ):
        tr = await _agent_call(
            target_agent_id="oll1",
            message="run the analysis",
            from_agent_id="term1",
        )

    assert tr.data["delivered"] is True
    assert tr.data["delivered_to_chat"] is True
    mock_handler.assert_called_once_with(agent_id="oll1", text="run the analysis")


async def test_agent_call_openai_routes_to_send(setup):
    await _create_agent(agent_id="op1", template="openai")
    mock_handler = AsyncMock()
    with patch.dict("core.dispatch._DISPATCH", {"openai_send": mock_handler}):
        tr = await _agent_call(target_agent_id="op1", message="hi")
    assert tr.data["delivered_to_chat"] is True


async def test_agent_call_ai_bundle_no_handler(setup):
    """If bundle's _send handler not registered, delivered_to_chat stays False."""
    await _create_agent(agent_id="oll2", template="ollama")
    with patch.dict("core.dispatch._DISPATCH", {"ollama_send": None}):
        tr = await _agent_call(target_agent_id="oll2", message="hello")
    assert tr.data["delivered"] is True
    assert tr.data["delivered_to_chat"] is False
