"""Tests for agent_call dispatch — PTY delivery and fantastic_agent chat bridge."""

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


async def test_agent_call_fantastic_agent_routes_to_chat(setup):
    """agent_call to fantastic_agent routes through voice_transcript handler."""
    await _create_agent(agent_id="fa1", template="fantastic_agent")

    mock_handler = AsyncMock(return_value=None)
    with patch.dict(
        "core.dispatch._DISPATCH",
        {"voice_transcript": mock_handler},
    ):
        tr = await _agent_call(
            target_agent_id="fa1",
            message="run the analysis",
            from_agent_id="term1",
        )

    assert tr.data["delivered"] is True
    assert tr.data["delivered_to_chat"] is True
    assert tr.data["delivered_to_process"] is False
    # Verify the handler was called with correct args
    mock_handler.assert_called_once_with(
        agent_id="fa1",
        text="run the analysis",
        is_final=True,
        mode="chat",
    )


async def test_agent_call_fantastic_agent_no_handler(setup):
    """If voice_transcript handler not registered, delivered_to_chat stays False."""
    await _create_agent(agent_id="fa2", template="fantastic_agent")

    with patch.dict("core.dispatch._DISPATCH", {"voice_transcript": None}):
        tr = await _agent_call(target_agent_id="fa2", message="hello")

    assert tr.data["delivered"] is True
    assert tr.data["delivered_to_chat"] is False
