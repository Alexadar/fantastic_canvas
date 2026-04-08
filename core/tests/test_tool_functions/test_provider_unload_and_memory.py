"""Tests for provider unload, other providers generate_with_tools, and agent memory tools."""

from unittest.mock import AsyncMock, MagicMock, patch

from core.ai.provider import GenerationResult


# ─── Provider unload ─────────────────────────────────────────────────────


def test_integrated_stop_clears_model():
    """IntegratedProvider.stop() deletes model and tokenizer."""
    from core.ai.providers.integrated_provider import IntegratedProvider

    provider = IntegratedProvider(model="test")
    provider._model = MagicMock()
    provider._tokenizer = MagicMock()
    provider._ready = True

    provider.stop()

    assert provider._model is None
    assert provider._tokenizer is None
    assert provider._ready is False
    assert provider._stopped is True


def test_integrated_unload_calls_stop():
    """IntegratedProvider.unload() delegates to stop()."""
    from core.ai.providers.integrated_provider import IntegratedProvider

    provider = IntegratedProvider(model="test")
    provider._model = MagicMock()
    provider._tokenizer = MagicMock()

    provider.unload()

    assert provider._model is None
    assert provider._tokenizer is None


async def test_brain_swap_calls_unload():
    """Brain.swap_provider() calls unload() on old provider before swapping."""
    from core.ai.brain import AIBrain
    from pathlib import Path

    brain = AIBrain(Path("/tmp/test_unload"))

    old_provider = MagicMock()
    old_provider.unload = MagicMock()
    old_provider.stop = MagicMock()
    brain._provider = old_provider

    # Mock swap to fail early (we just want to verify unload is called)
    with patch.object(brain, "_auto_discover", AsyncMock(return_value=None)):
        try:
            await brain.swap_provider("ollama")
        except Exception:
            pass

    old_provider.unload.assert_called_once()


# ─── Anthropic generate_with_tools ──────────────────────────────────────


async def test_anthropic_generate_with_tools_text_only():
    from core.ai.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(model="claude-3-haiku-20240307", api_key="fake")

    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = "Hello world"

    mock_response = MagicMock()
    mock_response.content = [mock_text_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch.object(provider, "_get_client", return_value=mock_client):
        items = []
        async for item in provider.generate_with_tools(
            [{"role": "user", "content": "hi"}], []
        ):
            items.append(item)

    assert items[0] == "Hello world"
    assert isinstance(items[1], GenerationResult)
    assert items[1].text == "Hello world"
    assert items[1].tool_calls is None


async def test_anthropic_generate_with_tools_tool_call():
    from core.ai.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider(model="claude-3-haiku-20240307", api_key="fake")

    mock_tool_block = MagicMock()
    mock_tool_block.type = "tool_use"
    mock_tool_block.name = "list_agents"
    mock_tool_block.input = {}
    mock_tool_block.id = "toolu_123"

    mock_response = MagicMock()
    mock_response.content = [mock_tool_block]

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch.object(provider, "_get_client", return_value=mock_client):
        result = None
        async for item in provider.generate_with_tools(
            [{"role": "user", "content": "list agents"}], []
        ):
            if isinstance(item, GenerationResult):
                result = item

    assert result is not None
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "list_agents"
    assert result.tool_calls[0]["tool_use_id"] == "toolu_123"


# ─── Integrated generate_with_tools ─────────────────────────────────────


async def test_integrated_generate_with_tools_delegates():
    """IntegratedProvider.generate_with_tools delegates to generate() with no tool_calls."""
    from core.ai.providers.integrated_provider import IntegratedProvider

    provider = IntegratedProvider(model="test")

    async def mock_generate(messages):
        yield "Hello from local"

    provider.generate = mock_generate

    items = []
    async for item in provider.generate_with_tools([], []):
        items.append(item)

    assert items[0] == "Hello from local"
    assert isinstance(items[1], GenerationResult)
    assert items[1].text == "Hello from local"
    assert items[1].tool_calls is None


# ─── Proxy generate_with_tools ──────────────────────────────────────────


async def test_proxy_generate_with_tools_delegates():
    """ProxyProvider.generate_with_tools delegates to generate() with no tool_calls."""
    from core.ai.providers.proxy_provider import ProxyProvider

    provider = ProxyProvider(endpoint="http://fake:8888", model="test")

    async def mock_generate(messages):
        yield "Hello from proxy"

    provider.generate = mock_generate

    items = []
    async for item in provider.generate_with_tools([], []):
        items.append(item)

    assert items[0] == "Hello from proxy"
    assert isinstance(items[1], GenerationResult)
    assert items[1].text == "Hello from proxy"
    assert items[1].tool_calls is None


# ─── Agent memory tools ─────────────────────────────────────────────────


async def test_read_agent_memory_empty(setup):
    """read_agent_memory returns empty for agent with no memory."""
    from core.tools._agents import read_agent_memory

    engine = setup[0]
    agents = engine.store.list_agents()
    agent_id = agents[0]["id"]

    result = await read_agent_memory(agent_id)
    assert result["count"] == 0
    assert result["entries"] == []


async def test_append_and_read_agent_memory(setup):
    """append then read agent memory."""
    from core.tools._agents import append_agent_memory, read_agent_memory

    engine = setup[0]
    agents = engine.store.list_agents()
    agent_id = agents[0]["id"]

    # Append
    result = await append_agent_memory(
        agent_id, author_type=2, message={"note": "test note"}
    )
    assert "entry" in result
    assert result["entry"]["message"]["note"] == "test note"

    # Read
    result = await read_agent_memory(agent_id)
    assert result["count"] == 1
    assert result["entries"][0]["message"]["note"] == "test note"


async def test_read_agent_memory_not_found(setup):
    """read_agent_memory returns error for nonexistent agent."""
    from core.tools._agents import read_agent_memory

    result = await read_agent_memory("nonexistent_agent_xyz")
    assert "error" in result


async def test_append_agent_memory_no_message(setup):
    """append_agent_memory requires message."""
    from core.tools._agents import append_agent_memory

    engine = setup[0]
    agents = engine.store.list_agents()
    agent_id = agents[0]["id"]

    result = await append_agent_memory(agent_id, author_type=0, message=None)
    assert "error" in result


async def test_memory_tools_in_dispatch(setup):
    """Memory tools are registered in _TOOL_DISPATCH."""
    from core.dispatch import _TOOL_DISPATCH

    assert "read_agent_memory" in _TOOL_DISPATCH
    assert "append_agent_memory" in _TOOL_DISPATCH


async def test_memory_tools_in_ollama_schema(setup):
    """Memory tools appear in Ollama tool schema (not excluded)."""
    import core.ai.tool_schema as ts

    ts._cached_tools = None
    from core.ai.tool_schema import build_ollama_tools

    tools = build_ollama_tools()
    names = {t["function"]["name"] for t in tools}
    assert "read_agent_memory" in names
    assert "append_agent_memory" in names


# ─── No provider message ────────────────────────────────────────────────


async def test_respond_no_provider_shows_message(setup):
    """When no provider is configured, respond() returns helpful message."""
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)
    # Ensure no provider
    brain._provider = None

    printed = []
    result = await brain.respond("hello", print_fn=lambda t: printed.append(t))

    assert result is not None
    assert "not configured" in result.lower()
    assert "@ai start" in result
    assert len(printed) == 1
    assert "not configured" in printed[0].lower()


def test_no_provider_message_lists_providers():
    """_no_provider_message lists all registered providers."""
    from core.ai.brain import AIBrain
    from pathlib import Path

    brain = AIBrain(Path("/tmp/test_msg"))
    msg = brain._no_provider_message()
    assert "ollama" in msg
    assert "@ai start" in msg
