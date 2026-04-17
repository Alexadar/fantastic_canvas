"""Tests for agent_call dispatch — PTY delivery and AI bundle routing."""

from unittest.mock import AsyncMock, patch

from core.tools._process import _agent_call
from core.tools._agents import _create_agent


async def test_agent_call_not_found(setup):
    tr = await _agent_call(target_agent_id="nonexistent", message="hi")
    assert "error" in tr.data


async def test_agent_call_terminal_no_process(setup):
    """Terminal agent without a running process and no terminal_send handler
    → undelivered, explicit error. (No hardcoded `delivered:True`.)"""
    await _create_agent(agent_id="t1", template="terminal")
    tr = await _agent_call(target_agent_id="t1", message="hello")
    assert tr.data["delivered"] is False
    assert "no 'terminal_send' handler" in tr.data["error"]


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
    """If the bundle's `_send` handler is not registered → undelivered + error."""
    await _create_agent(agent_id="oll2", template="ollama")
    with patch.dict("core.dispatch._DISPATCH", {"ollama_send": None}):
        tr = await _agent_call(target_agent_id="oll2", message="hello")
    assert tr.data["delivered"] is False
    assert "no 'ollama_send' handler" in tr.data["error"]


async def test_agent_call_verb_routing(setup):
    """`verb=status` must resolve `{bundle}_status` in the dispatch registry."""
    await _create_agent(agent_id="oll3", template="ollama")
    mock_handler = AsyncMock(return_value=None)
    with patch.dict("core.dispatch._DISPATCH", {"ollama_status": mock_handler}):
        tr = await _agent_call(target_agent_id="oll3", verb="status")
    assert tr.data["delivered"] is True
    assert tr.data["verb"] == "status"
    mock_handler.assert_called_once_with(agent_id="oll3")


async def test_agent_call_verb_extra_kwargs(setup):
    """Extra kwargs to `agent_call` pass through to the resolved handler."""
    await _create_agent(agent_id="oll4", template="ollama")
    mock_handler = AsyncMock(return_value=None)
    with patch.dict("core.dispatch._DISPATCH", {"ollama_call": mock_handler}):
        tr = await _agent_call(
            target_agent_id="oll4", verb="call", tool="list_agents", args={}
        )
    assert tr.data["delivered"] is True
    mock_handler.assert_called_once_with(agent_id="oll4", tool="list_agents", args={})
