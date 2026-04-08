"""Tests for AI tool calling — schema converter, agentic loop, tool execution."""

import json
from unittest.mock import AsyncMock, patch, MagicMock


from core.ai.provider import GenerationResult
from core.ai.tool_schema import build_ollama_tools


# ─── tool_schema.py ─────────────────────────────────────────────────────


async def test_build_ollama_tools_returns_list(setup):
    from core.ai.tool_schema import build_ollama_tools

    # Clear cache
    import core.ai.tool_schema as ts

    ts._cached_tools = None

    tools = build_ollama_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0


async def test_build_ollama_tools_format(setup):
    import core.ai.tool_schema as ts

    ts._cached_tools = None

    tools = build_ollama_tools()
    for t in tools:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "description" in t["function"]
        assert "parameters" in t["function"]


async def test_build_ollama_tools_excludes_ai_prefix(setup):
    import core.ai.tool_schema as ts

    ts._cached_tools = None

    tools = build_ollama_tools()
    names = [t["function"]["name"] for t in tools]
    ai_tools = [n for n in names if n.startswith("ai_")]
    assert ai_tools == [], f"ai_* tools should be excluded: {ai_tools}"


async def test_build_ollama_tools_includes_core_tools(setup):
    import core.ai.tool_schema as ts

    ts._cached_tools = None

    tools = build_ollama_tools()
    names = {t["function"]["name"] for t in tools}
    assert "create_agent" in names
    assert "execute_python" in names
    assert "list_agents" in names


async def test_build_ollama_tools_cached(setup):
    import core.ai.tool_schema as ts

    ts._cached_tools = None

    tools1 = build_ollama_tools()
    tools2 = build_ollama_tools()
    assert tools1 is tools2  # same object, not a copy


# ─── GenerationResult ───────────────────────────────────────────────────


def test_generation_result_text_only():
    r = GenerationResult(text="hello", tool_calls=None)
    assert r.text == "hello"
    assert r.tool_calls is None


def test_generation_result_with_calls():
    r = GenerationResult(
        text="",
        tool_calls=[{"name": "list_agents", "arguments": {}}],
    )
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0]["name"] == "list_agents"


# ─── OllamaProvider.generate_with_tools (mocked) ────────────────────────


def _make_ollama_mock(chunks):
    """Create a mock ollama client whose chat() returns an async iterable."""

    class AsyncStream:
        def __init__(self, data):
            self._data = data
            self._idx = 0

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._idx >= len(self._data):
                raise StopAsyncIteration
            item = self._data[self._idx]
            self._idx += 1
            return item

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=AsyncStream(chunks))
    return mock_client


async def test_generate_with_tools_text_only():
    from core.ai.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(endpoint="http://fake:11434", model="test")
    mock_client = _make_ollama_mock(
        [
            {"message": {"content": "Hello "}},
            {"message": {"content": "world"}},
        ]
    )

    with patch.object(provider, "_get_client", return_value=mock_client):
        tokens = []
        result = None
        async for item in provider.generate_with_tools([], []):
            if isinstance(item, GenerationResult):
                result = item
            else:
                tokens.append(item)

    assert tokens == ["Hello ", "world"]
    assert result is not None
    assert result.text == "Hello world"
    assert result.tool_calls is None


async def test_generate_with_tools_with_tool_call():
    from core.ai.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(endpoint="http://fake:11434", model="test")
    mock_client = _make_ollama_mock(
        [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "list_agents", "arguments": {}}}
                    ],
                }
            },
        ]
    )

    with patch.object(provider, "_get_client", return_value=mock_client):
        result = None
        async for item in provider.generate_with_tools([], []):
            if isinstance(item, GenerationResult):
                result = item

    assert result is not None
    assert result.tool_calls is not None
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0]["name"] == "list_agents"


async def test_generate_with_tools_streams_tokens():
    from core.ai.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(endpoint="http://fake:11434", model="test")
    mock_client = _make_ollama_mock(
        [
            {"message": {"content": "a"}},
            {"message": {"content": "b"}},
            {"message": {"content": "c"}},
        ]
    )

    with patch.object(provider, "_get_client", return_value=mock_client):
        items = []
        async for item in provider.generate_with_tools([], []):
            items.append(item)

    assert items[0] == "a"
    assert items[1] == "b"
    assert items[2] == "c"
    assert isinstance(items[3], GenerationResult)


# ─── brain._execute_tool ────────────────────────────────────────────────


async def test_execute_tool_success(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    result = await brain._execute_tool("list_agents", {})
    # Should return a JSON string (list of agents)
    parsed = json.loads(result)
    assert isinstance(parsed, list)


async def test_execute_tool_unknown(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    result = await brain._execute_tool("nonexistent_tool_xyz", {})
    assert "Error: unknown tool" in result


async def test_execute_tool_exception(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    # execute_python without agent_id should error
    result = await brain._execute_tool("execute_python", {"code": "print(1)"})
    assert "Error" in result or "error" in result.lower()


# ─── brain agentic loop (mocked provider) ───────────────────────────────


def _make_mock_provider(rounds):
    """Create a mock provider that yields predetermined rounds.

    rounds: list of (text, tool_calls_or_none) tuples.
    Each round, generate_with_tools yields text tokens then GenerationResult.
    """
    round_iter = iter(rounds)

    class MockProvider:
        async def generate_with_tools(self, messages, tools):
            text, tool_calls = next(round_iter)
            if text:
                for ch in text:
                    yield ch
            yield GenerationResult(text=text or "", tool_calls=tool_calls)

    return MockProvider()


async def test_respond_no_tool_calls(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)
    provider = _make_mock_provider([("Hello!", None)])
    brain._provider = provider

    result = await brain.respond("hi")
    assert result == "Hello!"


async def test_respond_single_tool_call(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    # Round 1: tool call, Round 2: text response
    provider = _make_mock_provider(
        [
            ("", [{"name": "list_agents", "arguments": {}}]),
            ("Done!", None),
        ]
    )
    brain._provider = provider

    tokens = []
    result = await brain.respond("list agents", print_fn=lambda t: tokens.append(t))
    assert result == "Done!"


async def test_respond_multi_tool_chain(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    provider = _make_mock_provider(
        [
            ("", [{"name": "list_agents", "arguments": {}}]),
            ("", [{"name": "get_state", "arguments": {}}]),
            ("All done.", None),
        ]
    )
    brain._provider = provider

    result = await brain.respond("do stuff")
    assert result == "All done."


async def test_respond_max_rounds_limit(setup):
    from core.ai.brain import AIBrain, MAX_TOOL_ROUNDS

    brain = AIBrain(setup[0].project_dir)

    # Provider always returns tool calls — should stop at MAX_TOOL_ROUNDS
    endless_rounds = [
        ("", [{"name": "list_agents", "arguments": {}}])
        for _ in range(MAX_TOOL_ROUNDS + 5)
    ]
    provider = _make_mock_provider(endless_rounds)
    brain._provider = provider

    await brain.respond("loop forever")
    # Should have stopped — not crashed


async def test_respond_tool_result_in_messages(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    messages_seen = []

    class TrackingProvider:
        async def generate_with_tools(self, messages, tools):
            messages_seen.append(list(messages))
            if len(messages_seen) == 1:
                yield GenerationResult(
                    text="", tool_calls=[{"name": "list_agents", "arguments": {}}]
                )
            else:
                yield "ok"
                yield GenerationResult(text="ok", tool_calls=None)

    brain._provider = TrackingProvider()

    await brain.respond("test")

    # Second call should have tool result in messages
    assert len(messages_seen) == 2
    second_msgs = messages_seen[1]
    tool_msgs = [m for m in second_msgs if m.get("role") == "tool"]
    assert len(tool_msgs) >= 1


async def test_respond_epoch_change_aborts(setup):
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    class EpochBreaker:
        async def generate_with_tools(self, messages, tools):
            # Bump epoch to simulate provider swap
            brain._generation_epoch += 1
            yield GenerationResult(
                text="", tool_calls=[{"name": "list_agents", "arguments": {}}]
            )

    brain._provider = EpochBreaker()

    await brain.respond("test")
    # Should return PROVIDER_CHANGING or None, not crash


# ─── Integration test ────────────────────────────────────────────────────


async def test_brain_executes_real_tool(setup):
    """Mock provider calls list_agents, verify it actually executes."""
    from core.ai.brain import AIBrain

    brain = AIBrain(setup[0].project_dir)

    call_count = 0

    class RealToolProvider:
        async def generate_with_tools(self, messages, tools):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield GenerationResult(
                    text="",
                    tool_calls=[{"name": "list_agents", "arguments": {}}],
                )
            else:
                # Check that tool result is in messages
                tool_msgs = [m for m in messages if m.get("role") == "tool"]
                content = tool_msgs[0]["content"] if tool_msgs else ""
                yield f"Found agents: {content[:50]}"
                yield GenerationResult(
                    text=f"Found agents: {content[:50]}", tool_calls=None
                )

    brain._provider = RealToolProvider()

    result = await brain.respond("what agents exist?")
    assert result is not None
    assert "Found agents" in result
    assert call_count == 2
