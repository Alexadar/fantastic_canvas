"""Tests for core.ai.anthropic_provider — Anthropic API provider."""

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import os

import pytest

from core.ai.anthropic_provider import AnthropicProvider, DEFAULT_MODEL


# ─── discover ────────────────────────────────────────────


async def test_discover_no_package():
    """discover() fails gracefully when anthropic is not installed."""
    with patch.dict("sys.modules", {"anthropic": None}):
        # Force ImportError
        with patch("builtins.__import__", side_effect=_import_raiser("anthropic")):
            result = await AnthropicProvider.discover()
    assert result.available is False
    assert "not installed" in result.error
    assert "uv pip install" in result.error


async def test_discover_no_api_key():
    """discover() fails when ANTHROPIC_API_KEY is not set."""
    with patch.dict(os.environ, {}, clear=True):
        # Make sure anthropic is importable (mock it)
        mock_anthropic = MagicMock()
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = await AnthropicProvider.discover()
    assert result.available is False
    assert "ANTHROPIC_API_KEY" in result.error


async def test_discover_available():
    """discover() succeeds with key + working API."""
    mock_anthropic = MagicMock()
    mock_client = MagicMock()

    mock_model = MagicMock()
    mock_model.id = "claude-sonnet-4-20250514"
    mock_page = MagicMock()
    mock_page.data = [mock_model]
    mock_client.models.list = AsyncMock(return_value=mock_page)

    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = await AnthropicProvider.discover()

    assert result.available is True
    assert result.provider_name == "anthropic"
    assert "claude-sonnet-4-20250514" in result.models


async def test_discover_models_list_fails_still_available():
    """discover() still succeeds if models.list fails (falls back to default)."""
    mock_anthropic = MagicMock()
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=Exception("forbidden"))
    mock_anthropic.AsyncAnthropic.return_value = mock_client

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-key"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = await AnthropicProvider.discover()

    assert result.available is True
    assert DEFAULT_MODEL in result.models


async def test_discover_client_creation_fails():
    """discover() fails when AsyncAnthropic constructor raises."""
    mock_anthropic = MagicMock()
    mock_anthropic.AsyncAnthropic.side_effect = Exception("bad key format")

    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "invalid"}):
        with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
            result = await AnthropicProvider.discover()

    assert result.available is False
    assert "bad key format" in result.error


# ─── generate ────────────────────────────────────────────


async def test_generate_streams_tokens():
    """generate() streams tokens from the Messages API."""
    provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="sk-test")

    # Mock the streaming response
    mock_client = MagicMock()

    async def mock_text_stream():
        for token in ["Hello", " ", "world"]:
            yield token

    mock_stream_ctx = MagicMock()
    mock_stream_obj = MagicMock()
    mock_stream_obj.text_stream = mock_text_stream()

    # __aenter__ / __aexit__ for async with
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_obj)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)

    mock_client.messages.stream.return_value = mock_stream_ctx

    provider._client = mock_client

    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "hi"},
    ]

    tokens = []
    async for token in provider.generate(messages):
        tokens.append(token)

    assert tokens == ["Hello", " ", "world"]

    # Verify system was separated from messages
    call_kwargs = mock_client.messages.stream.call_args[1]
    assert call_kwargs["system"] == "You are helpful."
    assert call_kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"


async def test_generate_no_system_message():
    """generate() works without a system message."""
    provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="sk-test")

    mock_client = MagicMock()

    async def mock_text_stream():
        yield "ok"

    mock_stream_ctx = MagicMock()
    mock_stream_obj = MagicMock()
    mock_stream_obj.text_stream = mock_text_stream()
    mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_stream_obj)
    mock_stream_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_client.messages.stream.return_value = mock_stream_ctx

    provider._client = mock_client

    messages = [{"role": "user", "content": "hello"}]
    tokens = []
    async for token in provider.generate(messages):
        tokens.append(token)

    assert tokens == ["ok"]
    call_kwargs = mock_client.messages.stream.call_args[1]
    assert "system" not in call_kwargs


# ─── list_models ─────────────────────────────────────────


async def test_list_models():
    """list_models() returns model IDs from the API."""
    provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="sk-test")

    mock_client = MagicMock()
    m1, m2 = MagicMock(), MagicMock()
    m1.id = "claude-sonnet-4-20250514"
    m2.id = "claude-haiku-4-5-20251001"
    mock_page = MagicMock()
    mock_page.data = [m1, m2]
    mock_client.models.list = AsyncMock(return_value=mock_page)
    provider._client = mock_client

    models = await provider.list_models()
    assert models == ["claude-sonnet-4-20250514", "claude-haiku-4-5-20251001"]


async def test_list_models_fallback():
    """list_models() returns default model on API failure."""
    provider = AnthropicProvider(model="claude-sonnet-4-20250514", api_key="sk-test")

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=Exception("forbidden"))
    provider._client = mock_client

    models = await provider.list_models()
    assert models == [DEFAULT_MODEL]


# ─── pull ────────────────────────────────────────────────


async def test_pull_sets_model():
    """pull() just sets the model name (no download for API)."""
    provider = AnthropicProvider(model="old-model", api_key="sk-test")

    messages = []
    async for msg in provider.pull("claude-opus-4-20250514"):
        messages.append(msg)

    assert provider.model == "claude-opus-4-20250514"
    assert len(messages) == 1
    assert "no download" in messages[0]


# ─── model property ──────────────────────────────────────


def test_model_property():
    provider = AnthropicProvider(model="claude-sonnet-4-20250514")
    assert provider.model == "claude-sonnet-4-20250514"


def test_set_model():
    provider = AnthropicProvider(model="claude-sonnet-4-20250514")
    provider.set_model("claude-haiku-4-5-20251001")
    assert provider.model == "claude-haiku-4-5-20251001"


# ─── helpers ─────────────────────────────────────────────


def _import_raiser(blocked_name):
    """Return an __import__ replacement that raises ImportError for blocked_name."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _import(name, *args, **kwargs):
        if name == blocked_name:
            raise ImportError(f"No module named '{blocked_name}'")
        return real_import(name, *args, **kwargs)
    return _import
