"""Tests for fantastic_agent bundle — dispatch handlers, chat persistence, mic exclusivity."""

import json

import pytest

from core.dispatch import _DISPATCH
from core.tools import _TOOL_DISPATCH


# ── voice_transcript dispatch ─────────────────────────────────────


async def test_voice_transcript_empty(setup):
    """Empty text returns error."""
    handler = _DISPATCH["voice_transcript"]
    result = await handler(agent_id="a1", text="   ")
    assert "error" in result.data


async def test_voice_transcript_broadcasts_thinking_and_response(setup):
    """Transcript triggers thinking + voice_response broadcasts."""
    engine, bc, _ = setup
    bc.clear()

    handler = _DISPATCH["voice_transcript"]
    result = await handler(agent_id="a1", text="hello world")
    assert result.data.get("ok") is True

    thinking = bc.of_type("voice_state")
    assert any(m.get("state") == "thinking" for m in thinking)

    responses = bc.of_type("voice_response")
    assert len(responses) > 0
    # Last response should have done=True
    assert responses[-1]["done"] is True


async def test_voice_transcript_with_mode(setup):
    """Mode field is accepted without error."""
    engine, bc, _ = setup
    bc.clear()

    handler = _DISPATCH["voice_transcript"]
    result = await handler(agent_id="a1", text="hi", mode="chat")
    assert result.data.get("ok") is True


# ── voice_interrupt dispatch ──────────────────────────────────────


async def test_voice_interrupt(setup):
    """Interrupt broadcasts idle state."""
    engine, bc, _ = setup
    bc.clear()

    handler = _DISPATCH["voice_interrupt"]
    result = await handler(agent_id="a1")
    assert result.data.get("ok") is True

    states = bc.of_type("voice_state")
    assert any(m.get("state") == "idle" for m in states)


# ── voice_claim_mic / voice_release_mic ───────────────────────────


async def test_claim_mic_broadcasts_owner(setup):
    """Claiming mic broadcasts voice_mic_owner with agent_id."""
    engine, bc, _ = setup
    bc.clear()

    handler = _DISPATCH["voice_claim_mic"]
    result = await handler(agent_id="agent_1")
    assert result.data.get("ok") is True

    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 1
    assert owners[0]["agent_id"] == "agent_1"


async def test_claim_mic_second_agent_replaces(setup):
    """Second agent claiming mic replaces the first."""
    engine, bc, _ = setup

    await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    bc.clear()

    await _DISPATCH["voice_claim_mic"](agent_id="agent_2")
    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 1
    assert owners[0]["agent_id"] == "agent_2"


async def test_release_mic_clears_owner(setup):
    """Releasing mic when owned broadcasts null owner."""
    engine, bc, _ = setup

    await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    bc.clear()

    await _DISPATCH["voice_release_mic"](agent_id="agent_1")
    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 1
    assert owners[0]["agent_id"] is None


async def test_release_mic_wrong_agent_noop(setup):
    """Releasing mic by non-owner does not broadcast."""
    engine, bc, _ = setup

    await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    bc.clear()

    await _DISPATCH["voice_release_mic"](agent_id="agent_2")
    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 0


# ── chat_history dispatch ─────────────────────────────────────────


async def test_chat_history_empty(setup):
    """Empty history returns empty list."""
    handler = _DISPATCH["chat_history"]
    result = await handler(agent_id="no_history")
    assert result.data["messages"] == []


async def test_chat_history_after_transcript(setup):
    """Transcript persists messages and chat_history returns them."""
    engine, bc, _ = setup

    await _DISPATCH["voice_transcript"](agent_id="ch1", text="hello", mode="voice")
    result = await _DISPATCH["chat_history"](agent_id="ch1")

    messages = result.data["messages"]
    assert len(messages) == 2  # user + assistant
    assert messages[0]["role"] == "user"
    assert messages[0]["text"] == "hello"
    assert messages[0]["mode"] == "voice"
    assert messages[1]["role"] == "assistant"


# ── chat.json persistence ────────────────────────────────────────


async def test_chat_json_written(setup, tmp_path):
    """Chat messages are persisted to chat.json."""
    engine, bc, _ = setup

    await _DISPATCH["voice_transcript"](agent_id="persist1", text="test message", mode="chat")

    chat_path = tmp_path / ".fantastic" / "agents" / "persist1" / "chat.json"
    assert chat_path.exists()

    data = json.loads(chat_path.read_text())
    assert "messages" in data
    assert len(data["messages"]) == 2
    assert data["messages"][0]["mode"] == "chat"
    assert data["messages"][0]["text"] == "test message"
    assert "ts" in data["messages"][0]


# ── handbook tool ─────────────────────────────────────────────────


async def test_handbook_lists_skills(setup):
    """get_handbook_fantastic_agent without skill lists available skills."""
    handler = _DISPATCH["get_handbook_fantastic_agent"]
    result = await handler()
    assert "fantastic-agent" in result.data["text"]


async def test_handbook_specific_skill(setup):
    """get_handbook_fantastic_agent with skill returns content."""
    handler = _DISPATCH["get_handbook_fantastic_agent"]
    result = await handler(skill="fantastic-agent")
    assert "SKILL: fantastic-agent" in result.data["text"]
    assert "Voice Mode" in result.data["text"]


async def test_handbook_unknown_skill(setup):
    """Unknown skill returns error."""
    handler = _DISPATCH["get_handbook_fantastic_agent"]
    result = await handler(skill="nonexistent")
    assert "error" in result.data


# ── user-callable tool wrappers ───────────────────────────────────


async def test_tool_fantastic_agent_configure(setup):
    """fantastic_agent_configure sets/resets backend URL."""
    configure = _TOOL_DISPATCH["fantastic_agent_configure"]

    result = await configure(ai_backend_url="http://localhost:9999")
    assert "http://localhost:9999" in result

    result = await configure(ai_backend_url="")
    assert "echo stub" in result


async def test_tool_handbook_wrapper(setup):
    """get_handbook_fantastic_agent tool wrapper returns text."""
    handbook = _TOOL_DISPATCH["get_handbook_fantastic_agent"]
    result = await handbook()
    assert "fantastic-agent" in result
