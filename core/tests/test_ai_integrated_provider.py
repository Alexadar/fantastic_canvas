"""Tests for core.ai.integrated_provider — all torch/transformers mocked."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.ai.messages import AI_MSG


def _mock_torch(cuda=False, mps=False):
    """Create a mock torch module."""
    mod = MagicMock()
    mod.cuda.is_available.return_value = cuda
    backends = MagicMock()
    backends.mps.is_available.return_value = mps
    mod.backends = backends
    mod.float16 = "float16"
    mod.float32 = "float32"
    mod.bfloat16 = "bfloat16"
    mod.no_grad.return_value.__enter__ = MagicMock()
    mod.no_grad.return_value.__exit__ = MagicMock()
    return mod


def _mock_transformers():
    """Create a mock transformers module."""
    mod = MagicMock()
    return mod


# ─── discover ──────────────────────────────────────────────


async def test_discover_available_cpu():
    mock_torch = _mock_torch(cuda=False, mps=False)
    mock_tf = _mock_transformers()

    with patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}):
        from core.ai.integrated_provider import IntegratedProvider
        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.provider_name == "integrated"
    assert result.endpoint == "local:cpu"
    assert len(result.models) > 0


async def test_discover_available_cuda():
    mock_torch = _mock_torch(cuda=True, mps=False)
    mock_tf = _mock_transformers()

    with patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}):
        from core.ai.integrated_provider import IntegratedProvider
        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.endpoint == "local:cuda"


async def test_discover_available_mps():
    mock_torch = _mock_torch(cuda=False, mps=True)
    mock_tf = _mock_transformers()

    with patch.dict(sys.modules, {"torch": mock_torch, "transformers": mock_tf}):
        from core.ai.integrated_provider import IntegratedProvider
        result = await IntegratedProvider.discover()

    assert result.available is True
    assert result.endpoint == "local:mps"


async def test_discover_not_available():
    """When torch is not installed, discover returns unavailable."""
    with patch.dict(sys.modules, {"torch": None}):
        from core.ai.integrated_provider import IntegratedProvider
        result = await IntegratedProvider.discover()

    assert result.available is False
    assert "missing dependency" in (result.error or "")


# ─── model property ───────────────────────────────────────


def test_model_property():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="Qwen/Qwen3.5-9B")
    assert provider.model == "Qwen/Qwen3.5-9B"


def test_set_model():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="Qwen/Qwen3.5-4B")
    provider.set_model("Qwen/Qwen3.5-9B")
    assert provider.model == "Qwen/Qwen3.5-9B"
    assert provider.is_ready is False


def test_default_model():
    from core.ai.integrated_provider import IntegratedProvider, DEFAULT_MODEL
    provider = IntegratedProvider()
    assert provider.model == DEFAULT_MODEL


# ─── stop ─────────────────────────────────────────────────


def test_stop():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test")
    provider._ready = True
    provider._model = MagicMock()
    provider._tokenizer = MagicMock()

    provider.stop()

    assert provider.is_stopped is True
    assert provider.is_ready is False
    assert provider._model is None
    assert provider._tokenizer is None


# ─── chat when stopped ────────────────────────────────────


async def test_chat_when_stopped():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test")
    provider._stopped = True

    tokens = []
    async for token in provider.chat([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    assert tokens == [AI_MSG.PROVIDER_STOPPED]


# ─── chat with mocked model ──────────────────────────────


async def test_chat_generates_response():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test")

    # Simulate a loaded model
    provider._ready = True

    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = "formatted prompt"
    mock_tokenizer.return_value = {"input_ids": MagicMock(shape=[1, 10])}
    mock_tokenizer.decode.return_value = "Hello there!"

    mock_model = MagicMock()
    mock_model.device = "cpu"
    mock_model.generate.return_value = MagicMock(__getitem__=lambda s, i: list(range(15)))

    provider._model = mock_model
    provider._tokenizer = mock_tokenizer

    # Mock the executor to run synchronously
    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(return_value="Hello there!")

        tokens = []
        async for token in provider.chat([{"role": "user", "content": "hi"}]):
            tokens.append(token)

    assert tokens == ["Hello there!"]


# ─── load_model status_fn ────────────────────────────────


async def test_load_model_calls_status_fn():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test")

    statuses = []

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(
            return_value=(mock_model, mock_tokenizer)
        )
        await provider.load_model(status_fn=lambda s: statuses.append(s))

    assert AI_MSG.MODEL_DOWNLOADING in statuses
    assert AI_MSG.MODEL_READY in statuses
    assert provider.is_ready is True


async def test_load_model_stopped_during_load():
    """If stop() is called during load, model should not be set."""
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test")

    mock_model = MagicMock()
    mock_tokenizer = MagicMock()

    async def fake_executor(executor, fn):
        # Simulate stop during load
        provider._stopped = True
        return (mock_model, mock_tokenizer)

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = fake_executor
        await provider.load_model()

    assert provider.is_ready is False
    assert provider._model is None


# ─── pull ─────────────────────────────────────────────────


async def test_pull_changes_model():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="old-model")
    provider._ready = True

    messages = []
    async for msg in provider.pull("new-model"):
        messages.append(msg)

    assert provider.model == "new-model"
    assert provider.is_ready is False
    assert len(messages) == 1


# ─── list_models ──────────────────────────────────────────


async def test_list_models():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test-model")
    models = await provider.list_models()
    assert models == ["test-model"]


# ─── state properties ────────────────────────────────────


def test_initial_state():
    from core.ai.integrated_provider import IntegratedProvider
    provider = IntegratedProvider(model="test")
    assert provider.is_ready is False
    assert provider.is_loading is False
    assert provider.is_stopped is False
