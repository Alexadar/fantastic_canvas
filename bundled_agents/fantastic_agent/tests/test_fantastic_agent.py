"""Tests for fantastic_agent bundle — dispatch handlers, chat persistence, mic exclusivity."""

import json
from unittest.mock import AsyncMock, patch

from core.dispatch import _DISPATCH
from core.tools import _TOOL_DISPATCH
from core.ai.provider import GenerationResult


# ── Helper: mock provider that returns text ──────────────────────


def _mock_provider(text="Hello!"):
    """Create a mock provider whose generate_with_tools yields text then done."""
    class MockProvider:
        async def generate_with_tools(self, messages, tools):
            yield text
            yield GenerationResult(text=text, tool_calls=None)
    return MockProvider()


# ── voice_transcript dispatch ─────────────────────────────────────


async def test_voice_transcript_empty(setup):
    """Empty text returns error."""
    handler = _DISPATCH["voice_transcript"]
    result = await handler(agent_id="a1", text="   ")
    assert "error" in result.data


async def test_voice_transcript_no_provider(setup):
    """Without AI provider, returns error."""
    engine, bc, _ = setup
    bc.clear()
    # Ensure no provider
    engine.ai._provider = None

    handler = _DISPATCH["voice_transcript"]
    result = await handler(agent_id="a1", text="hello")

    errors = bc.of_type("voice_error")
    assert len(errors) >= 1


async def test_voice_transcript_broadcasts_thinking_and_response(setup):
    """Transcript triggers thinking + voice_response broadcasts."""
    engine, bc, _ = setup
    bc.clear()
    engine.ai._provider = _mock_provider("Hi there!")

    handler = _DISPATCH["voice_transcript"]
    result = await handler(agent_id="a1", text="hello")
    assert result.data.get("ok") is True

    thinking = bc.of_type("voice_state")
    assert any(m.get("state") == "thinking" for m in thinking)
    assert any(m.get("state") == "idle" for m in thinking)

    responses = bc.of_type("voice_response")
    assert len(responses) > 0
    assert responses[-1]["done"] is True


async def test_voice_transcript_with_mode(setup):
    """Mode field is accepted without error."""
    engine, bc, _ = setup
    bc.clear()
    engine.ai._provider = _mock_provider()

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
    engine, bc, _ = setup
    bc.clear()

    result = await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    assert result.data.get("ok") is True

    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 1
    assert owners[0]["agent_id"] == "agent_1"


async def test_claim_mic_second_agent_replaces(setup):
    engine, bc, _ = setup

    await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    bc.clear()

    await _DISPATCH["voice_claim_mic"](agent_id="agent_2")
    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 1
    assert owners[0]["agent_id"] == "agent_2"


async def test_release_mic_clears_owner(setup):
    engine, bc, _ = setup

    await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    bc.clear()

    await _DISPATCH["voice_release_mic"](agent_id="agent_1")
    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 1
    assert owners[0]["agent_id"] is None


async def test_release_mic_wrong_agent_noop(setup):
    engine, bc, _ = setup

    await _DISPATCH["voice_claim_mic"](agent_id="agent_1")
    bc.clear()

    await _DISPATCH["voice_release_mic"](agent_id="agent_2")
    owners = bc.of_type("voice_mic_owner")
    assert len(owners) == 0


# ── chat_history dispatch ─────────────────────────────────────────


async def test_chat_history_empty(setup):
    handler = _DISPATCH["chat_history"]
    result = await handler(agent_id="no_history")
    assert result.data["messages"] == []


async def test_chat_history_after_transcript(setup):
    engine, bc, _ = setup
    engine.ai._provider = _mock_provider("World!")

    await _DISPATCH["voice_transcript"](agent_id="ch1", text="hello", mode="voice")
    result = await _DISPATCH["chat_history"](agent_id="ch1")

    messages = result.data["messages"]
    assert len(messages) == 2  # user + assistant
    assert messages[0]["role"] == "user"
    assert messages[0]["text"] == "hello"
    assert messages[1]["role"] == "assistant"


# ── chat.json persistence ────────────────────────────────────────


async def test_chat_json_written(setup, tmp_path):
    engine, bc, _ = setup
    engine.ai._provider = _mock_provider("Response!")

    await _DISPATCH["voice_transcript"](agent_id="persist1", text="test message", mode="chat")

    chat_path = tmp_path / ".fantastic" / "agents" / "persist1" / "chat.json"
    assert chat_path.exists()

    data = json.loads(chat_path.read_text())
    assert "messages" in data
    assert len(data["messages"]) == 2
    assert data["messages"][0]["mode"] == "chat"
    assert data["messages"][0]["text"] == "test message"


# ── handbook tool ─────────────────────────────────────────────────


async def test_handbook_lists_skills(setup):
    handler = _DISPATCH["get_handbook_fantastic_agent"]
    result = await handler()
    assert "fantastic-agent" in result.data["text"]


async def test_handbook_specific_skill(setup):
    handler = _DISPATCH["get_handbook_fantastic_agent"]
    result = await handler(skill="fantastic-agent")
    assert "SKILL: fantastic-agent" in result.data["text"]


async def test_handbook_unknown_skill(setup):
    handler = _DISPATCH["get_handbook_fantastic_agent"]
    result = await handler(skill="nonexistent")
    assert "error" in result.data


# ── user-callable tool wrappers ───────────────────────────────────


async def test_tool_handbook_wrapper(setup):
    handbook = _TOOL_DISPATCH["get_handbook_fantastic_agent"]
    result = await handbook()
    assert "fantastic-agent" in result
