"""Tests for OpenAICompatibleProvider — mocked httpx, no real HTTP."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from core.ai.providers.openai_compat_provider import (
    OpenAICompatibleProvider,
    DEFAULT_ENDPOINT,
)
from core.ai.provider import GenerationResult


# ─── helpers ──────────────────────────────────────────────


class MockAsyncLineIterator:
    """Simulate httpx response.aiter_lines()."""

    def __init__(self, lines: list[str]):
        self._lines = lines

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class MockStreamResponse:
    """Mock httpx streaming response (async context manager)."""

    def __init__(self, lines: list[str], status_code: int = 200):
        self._lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock()
            )

    async def aread(self):
        return b"internal server error"

    def aiter_lines(self):
        return MockAsyncLineIterator(list(self._lines))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _sse_line(delta: dict) -> str:
    """Build an SSE data line from a delta dict."""
    return f'data: {json.dumps({"choices": [{"delta": delta}]})}'


# ─── discover ────────────────────────────────────────���────


async def test_discover_available():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "llama3"}, {"id": "qwen2.5"}]}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_resp
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await OpenAICompatibleProvider.discover()

    assert result.available is True
    assert result.models == ["llama3", "qwen2.5"]
    assert result.endpoint == DEFAULT_ENDPOINT
    assert result.provider_name == "openai"
    assert result.error is None


async def test_discover_custom_endpoint():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "m1"}]}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_resp
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await OpenAICompatibleProvider.discover("http://remote:9090/v1")

    assert result.available is True
    assert result.endpoint == "http://remote:9090/v1"


async def test_discover_no_models():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": []}

    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_resp
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await OpenAICompatibleProvider.discover()

    assert result.available is True
    assert result.models == []


async def test_discover_connection_error():
    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.side_effect = httpx.ConnectError("refused")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await OpenAICompatibleProvider.discover()

    assert result.available is False
    assert result.error is not None


async def test_discover_timeout():
    with patch("httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.side_effect = httpx.TimeoutException("timed out")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await OpenAICompatibleProvider.discover()

    assert result.available is False
    assert "timed out" in (result.error or "")


# ─── generate ─────────────────────────────────────────────


async def test_generate_streams_tokens():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    lines = [
        _sse_line({"content": "Hello"}),
        _sse_line({"content": " world"}),
        _sse_line({"content": ""}),  # empty — should be skipped
        "data: [DONE]",
    ]

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse(lines)
    provider._client = mock_client

    tokens = []
    async for token in provider.generate([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    assert tokens == ["Hello", " world"]


async def test_generate_handles_done():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    lines = [
        _sse_line({"content": "ok"}),
        "data: [DONE]",
        _sse_line({"content": "should not appear"}),
    ]

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse(lines)
    provider._client = mock_client

    tokens = []
    async for token in provider.generate([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    assert tokens == ["ok"]


# ─── generate_with_tools ─────────────────────────────────


async def test_generate_with_tools_text_only():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    lines = [
        _sse_line({"content": "No tools needed."}),
        "data: [DONE]",
    ]

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse(lines)
    provider._client = mock_client

    results = []
    async for item in provider.generate_with_tools(
        [{"role": "user", "content": "hi"}], []
    ):
        results.append(item)

    # Tokens + final GenerationResult
    assert results[0] == "No tools needed."
    assert isinstance(results[-1], GenerationResult)
    assert results[-1].text == "No tools needed."
    assert results[-1].tool_calls is None


async def test_generate_with_tools_with_calls():
    """Simulate incremental tool_calls: name on first chunk, arguments across chunks."""
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    lines = [
        _sse_line({"content": "Let me check."}),
        # First tool_call chunk: index 0, function name + start of arguments
        _sse_line(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {"name": "list_agents", "arguments": '{"par'},
                    }
                ]
            }
        ),
        # Second chunk: continue arguments
        _sse_line(
            {
                "tool_calls": [
                    {"index": 0, "function": {"arguments": 'ent": ""}'}}
                ]
            }
        ),
        "data: [DONE]",
    ]

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse(lines)
    provider._client = mock_client

    results = []
    async for item in provider.generate_with_tools(
        [{"role": "user", "content": "list agents"}],
        [{"type": "function", "function": {"name": "list_agents"}}],
    ):
        results.append(item)

    # First yield is the text token
    assert results[0] == "Let me check."
    # Last yield is GenerationResult
    gen = results[-1]
    assert isinstance(gen, GenerationResult)
    assert gen.text == "Let me check."
    assert gen.tool_calls is not None
    assert len(gen.tool_calls) == 1
    assert gen.tool_calls[0]["name"] == "list_agents"
    assert gen.tool_calls[0]["arguments"] == {"parent": ""}


async def test_generate_with_tools_multiple_calls():
    """Two tool calls in one response."""
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    lines = [
        _sse_line(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "function": {
                            "name": "list_agents",
                            "arguments": "{}",
                        },
                    },
                    {
                        "index": 1,
                        "function": {
                            "name": "get_state",
                            "arguments": "{}",
                        },
                    },
                ]
            }
        ),
        "data: [DONE]",
    ]

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse(lines)
    provider._client = mock_client

    results = []
    async for item in provider.generate_with_tools(
        [{"role": "user", "content": "status"}], []
    ):
        results.append(item)

    gen = results[-1]
    assert isinstance(gen, GenerationResult)
    assert len(gen.tool_calls) == 2
    assert gen.tool_calls[0]["name"] == "list_agents"
    assert gen.tool_calls[1]["name"] == "get_state"


# ─── list_models ──────────────────────────────────────────


async def test_list_models():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": [{"id": "llama3"}, {"id": "qwen2.5"}]}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    provider._client = mock_client

    models = await provider.list_models()
    assert models == ["llama3", "qwen2.5"]


async def test_list_models_empty():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": []}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    provider._client = mock_client

    assert await provider.list_models() == []


# ─── pull ─────────────────────────────────────────────────


async def test_pull_noop():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")
    messages = []
    async for msg in provider.pull("new-model"):
        messages.append(msg)
    assert len(messages) == 1
    assert "new-model" in messages[0]
    assert provider.model == "new-model"


# ─── model property ───────────────────────────────────────


def test_model_property():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")
    assert provider.model == "llama3"


def test_set_model():
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")
    provider.set_model("qwen2.5")
    assert provider.model == "qwen2.5"


# ─── endpoint stripping ──────────────────────────────────


async def test_generate_server_error():
    """HTTP 500 raises RuntimeError with server response body, not HTTPStatusError."""
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse([], status_code=500)
    provider._client = mock_client

    import pytest

    with pytest.raises(RuntimeError, match="server error 500"):
        async for _ in provider.generate([{"role": "user", "content": "hi"}]):
            pass


async def test_generate_with_tools_server_error():
    """HTTP 500 in generate_with_tools raises RuntimeError."""
    provider = OpenAICompatibleProvider(DEFAULT_ENDPOINT, "llama3")

    mock_client = MagicMock()
    mock_client.stream.return_value = MockStreamResponse([], status_code=500)
    provider._client = mock_client

    import pytest

    with pytest.raises(RuntimeError, match="server error 500"):
        async for _ in provider.generate_with_tools(
            [{"role": "user", "content": "hi"}], []
        ):
            pass


def test_endpoint_trailing_slash_stripped():
    provider = OpenAICompatibleProvider("http://localhost:8080/v1/", "m")
    assert provider._endpoint == "http://localhost:8080/v1"
