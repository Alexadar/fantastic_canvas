"""Tests for core.ai.ollama_provider — OllamaProvider with mocked ollama client."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch


from core.ai.ollama_provider import OllamaProvider, DEFAULT_ENDPOINT


def _make_ollama_mock(client_mock):
    """Create a mock ollama module with AsyncClient returning client_mock."""
    mod = MagicMock()
    mod.AsyncClient.return_value = client_mock
    return mod


# ─── discover ──────────────────────────────────────────────


async def test_discover_available():
    mock_model = MagicMock()
    mock_model.model = "llama3.2"
    mock_resp = MagicMock()
    mock_resp.models = [mock_model]

    mock_client = AsyncMock()
    mock_client.list.return_value = mock_resp

    with patch.dict(sys.modules, {"ollama": _make_ollama_mock(mock_client)}):
        result = await OllamaProvider.discover()

    assert result.available is True
    assert result.models == ["llama3.2"]
    assert result.endpoint == DEFAULT_ENDPOINT
    assert result.provider_name == "ollama"
    assert result.error is None


async def test_discover_custom_endpoint():
    mock_resp = MagicMock()
    mock_resp.models = []
    mock_client = AsyncMock()
    mock_client.list.return_value = mock_resp

    with patch.dict(sys.modules, {"ollama": _make_ollama_mock(mock_client)}):
        result = await OllamaProvider.discover("http://remote:11434")

    assert result.available is True
    assert result.endpoint == "http://remote:11434"


async def test_discover_no_models():
    mock_resp = MagicMock()
    mock_resp.models = []
    mock_client = AsyncMock()
    mock_client.list.return_value = mock_resp

    with patch.dict(sys.modules, {"ollama": _make_ollama_mock(mock_client)}):
        result = await OllamaProvider.discover()

    assert result.available is True
    assert result.models == []


async def test_discover_import_error():
    # Remove ollama from sys.modules to trigger ImportError
    with patch.dict(sys.modules, {"ollama": None}):
        result = await OllamaProvider.discover()

    assert result.available is False
    assert "ollama" in (result.error or "").lower()


async def test_discover_connection_error():
    mock_client = AsyncMock()
    mock_client.list.side_effect = ConnectionError("refused")

    with patch.dict(sys.modules, {"ollama": _make_ollama_mock(mock_client)}):
        result = await OllamaProvider.discover()

    assert result.available is False
    assert result.error is not None


# ─── generate ──────────────────────────────────────────────


async def test_generate_streams_tokens():
    provider = OllamaProvider(DEFAULT_ENDPOINT, "llama3.2")

    chunks = [
        {"message": {"content": "Hello"}},
        {"message": {"content": " world"}},
        {"message": {"content": ""}},  # empty chunk, should be skipped
    ]

    async def mock_stream():
        for c in chunks:
            yield c

    mock_client = AsyncMock()
    mock_client.chat.return_value = mock_stream()
    provider._client = mock_client

    tokens = []
    async for token in provider.generate([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    assert tokens == ["Hello", " world"]
    mock_client.chat.assert_called_once_with(
        model="llama3.2",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
    )


# ─── list_models ───────────────────────────────────────────


async def test_list_models():
    provider = OllamaProvider(DEFAULT_ENDPOINT, "llama3.2")

    m1 = MagicMock()
    m1.model = "llama3.2"
    m2 = MagicMock()
    m2.model = "qwen2.5"
    mock_resp = MagicMock()
    mock_resp.models = [m1, m2]

    mock_client = AsyncMock()
    mock_client.list.return_value = mock_resp
    provider._client = mock_client

    models = await provider.list_models()
    assert models == ["llama3.2", "qwen2.5"]


async def test_list_models_empty():
    provider = OllamaProvider(DEFAULT_ENDPOINT, "llama3.2")

    mock_resp = MagicMock()
    mock_resp.models = []
    mock_client = AsyncMock()
    mock_client.list.return_value = mock_resp
    provider._client = mock_client

    assert await provider.list_models() == []


# ─── pull ──────────────────────────────────────────────────


async def test_pull_yields_progress():
    provider = OllamaProvider(DEFAULT_ENDPOINT, "llama3.2")

    progress_events = [
        {"status": "downloading", "total": 1000, "completed": 500},
        {"status": "downloading", "total": 1000, "completed": 1000},
        {"status": "success", "total": 0, "completed": 0},
    ]

    async def mock_stream():
        for p in progress_events:
            yield p

    mock_client = AsyncMock()
    mock_client.pull.return_value = mock_stream()
    provider._client = mock_client

    progress = []
    async for p in provider.pull("llama3.2"):
        progress.append(p)

    assert progress == ["downloading 50%", "downloading 100%", "success"]


# ─── model property ───────────────────────────────────────


def test_model_property():
    provider = OllamaProvider(DEFAULT_ENDPOINT, "llama3.2")
    assert provider.model == "llama3.2"


def test_set_model():
    provider = OllamaProvider(DEFAULT_ENDPOINT, "llama3.2")
    provider.set_model("qwen2.5")
    assert provider.model == "qwen2.5"
