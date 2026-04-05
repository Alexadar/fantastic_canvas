"""Tests for core.ai.brain — AIBrain orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.ai.brain import AIBrain
from core.ai.config import save_config
from core.ai.provider import DiscoverResult
from core import conversation


def setup_function():
    conversation.clear()


# ─── ensure_provider ──────────────────────────────────────


async def test_ensure_provider_from_config(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)
    provider = await brain.ensure_provider()
    assert provider is not None
    assert provider.model == "llama3.2"


async def test_ensure_provider_caches(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)
    p1 = await brain.ensure_provider()
    p2 = await brain.ensure_provider()
    assert p1 is p2


async def test_ensure_provider_auto_discover(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(
        available=True,
        models=["llama3.2"],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )

    with patch("core.ai.brain._PROVIDERS") as mock_providers:
        mock_cls = MagicMock()
        mock_cls.discover = AsyncMock(return_value=mock_result)
        mock_cls.return_value = MagicMock(model="llama3.2")
        mock_providers.__iter__ = lambda self: iter(
            [(mock_cls, "http://localhost:11434")]
        )

        provider = await brain.ensure_provider()

    assert provider is not None


async def test_ensure_provider_no_provider(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(
        available=False,
        provider_name="ollama",
        error="not running",
    )

    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        provider = await brain.ensure_provider()

    assert provider is None


async def test_auto_discover_available_no_models(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(
        available=True,
        models=[],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )

    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        provider = await brain.ensure_provider()

    assert provider is None
    # Should have told user about missing models
    entries = conversation.read()
    assert any("no models" in e["message"].lower() for e in entries)


async def test_ensure_provider_unknown_provider_in_config(project_dir):
    save_config(
        project_dir,
        {
            "provider": "unknown_provider",
            "endpoint": "http://localhost:9999",
            "model": "foo",
        },
    )
    brain = AIBrain(project_dir)

    # Config has unknown provider, so _provider_from_config returns None.
    # Then auto-discover runs. Mock it to also fail.
    mock_result = DiscoverResult(available=False, provider_name="ollama", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        provider = await brain.ensure_provider()

    assert provider is None


# ─── _build_messages ──────────────────────────────────────


def test_build_messages_with_history(project_dir):
    conversation.say("user", "hello")
    conversation.say("ai", "hi there")
    conversation.say("system", "internal note")

    brain = AIBrain(project_dir)
    msgs = brain._build_messages("what's up?")

    assert msgs[0]["role"] == "system"
    assert "Fantastic Canvas" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "hello"}
    assert msgs[2] == {"role": "assistant", "content": "hi there"}
    # system/fantastic messages are skipped
    assert msgs[3] == {"role": "user", "content": "what's up?"}
    assert len(msgs) == 4


def test_build_messages_empty_history(project_dir):
    brain = AIBrain(project_dir)
    msgs = brain._build_messages("hi")
    assert len(msgs) == 2  # system + current input
    assert msgs[0]["role"] == "system"
    assert msgs[1] == {"role": "user", "content": "hi"}


# ─── respond ──────────────────────────────────────────────


async def test_respond_streams_and_saves(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)

    async def mock_chat(messages):
        for token in ["Hello", " world"]:
            yield token

    provider = await brain.ensure_provider()
    provider.generate = mock_chat

    printed = []
    response = await brain.respond("hi", print_fn=lambda t: printed.append(t))

    assert response == "Hello world"
    assert printed == ["Hello", " world"]

    # Check it was written to conversation buffer
    entries = conversation.read()
    assert any(e["who"] == "ai" and e["message"] == "Hello world" for e in entries)


async def test_respond_no_provider(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="ollama", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        result = await brain.respond("hi")

    assert result is None


async def test_respond_empty_response(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)

    async def mock_chat(messages):
        return
        yield  # make it an async generator that yields nothing

    provider = await brain.ensure_provider()
    provider.generate = mock_chat

    response = await brain.respond("hi")
    assert response == ""


# ─── status ───────────────────────────────────────────────


async def test_status_unconfigured(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="ollama", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        status = await brain.status()

    assert status["configured"] is False
    assert status["connected"] is False
    assert status["provider"] is None
    assert status["model"] is None


async def test_status_configured(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)
    status = await brain.status()

    assert status["configured"] is True
    assert status["connected"] is True
    assert status["provider"] == "ollama"
    assert status["model"] == "llama3.2"
    assert status["endpoint"] == "http://localhost:11434"


# ─── models ───────────────────────────────────────────────


async def test_models_with_provider(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)
    provider = await brain.ensure_provider()
    provider.list_models = AsyncMock(return_value=["llama3.2", "qwen2.5"])

    models = await brain.models()
    assert models == ["llama3.2", "qwen2.5"]


async def test_models_no_provider(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="ollama", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        models = await brain.models()

    assert models == []


# ─── set_model ────────────────────────────────────────────


async def test_set_model(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)
    await brain.ensure_provider()

    await brain.set_model("qwen2.5")

    assert brain.provider.model == "qwen2.5"
    # Check config was persisted
    from core.ai.config import load_config

    config = load_config(project_dir)
    assert config["model"] == "qwen2.5"

    # Check conversation
    entries = conversation.read()
    assert any("qwen2.5" in e["message"] for e in entries)


async def test_set_model_no_provider(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="ollama", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        with pytest.raises(RuntimeError, match="No AI provider"):
            await brain.set_model("foo")


# ─── pull_model ───────────────────────────────────────────


async def test_pull_model(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    brain = AIBrain(project_dir)
    provider = await brain.ensure_provider()

    async def mock_pull(model):
        yield "downloading 50%"
        yield "downloading 100%"
        yield "success"

    provider.pull = mock_pull

    printed = []
    await brain.pull_model("qwen2.5", print_fn=lambda s: printed.append(s))

    assert len(printed) == 4  # 3 progress + "pulled qwen2.5"
    entries = conversation.read()
    assert any("pulled model: qwen2.5" in e["message"] for e in entries)


async def test_pull_model_no_provider(project_dir):
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="ollama", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        with pytest.raises(RuntimeError, match="No AI provider"):
            await brain.pull_model("foo")
