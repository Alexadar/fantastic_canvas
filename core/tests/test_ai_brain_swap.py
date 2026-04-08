"""Tests for AIBrain stop/start/swap/configure — provider lifecycle management."""

from unittest.mock import AsyncMock, MagicMock, patch


from core.ai.brain import AIBrain, _PROVIDER_MAP
from core.ai.config import save_config, load_config
from core.ai.messages import AI_MSG
from core.ai.provider import DiscoverResult
from core import conversation


def setup_function():
    conversation.clear()


# ─── stop_provider ────────────────────────────────────────


async def test_stop_provider_none(project_dir):
    """Stopping when no provider is running returns appropriate message."""
    brain = AIBrain(project_dir)
    result = await brain.stop_provider()
    assert result == AI_MSG.NO_PROVIDER


async def test_stop_provider_ollama(project_dir):
    """Stopping an ollama provider clears it."""
    save_config(
        project_dir,
        {
            "provider_name": "ollama",
            "provider_config": {
                "endpoint": "http://localhost:11434",
                "model": "llama3.2",
            },
        },
    )
    brain = AIBrain(project_dir)
    await brain.ensure_provider()
    assert brain.provider is not None

    result = await brain.stop_provider()

    assert "stopped" in result
    assert brain.provider is None


async def test_stop_provider_with_stop_method(project_dir):
    """Providers with a stop() method get it called."""
    brain = AIBrain(project_dir)
    mock_provider = MagicMock()
    mock_provider.stop = MagicMock()
    brain._provider = mock_provider

    save_config(
        project_dir,
        {"provider_name": "integrated", "provider_config": {"model": "test"}},
    )

    await brain.stop_provider()

    mock_provider.stop.assert_called_once()
    assert brain.provider is None


# ─── start_provider ──────────────────────────────────────


async def test_start_provider_already_running(project_dir):
    """Starting when already running returns already running message."""
    save_config(
        project_dir,
        {
            "provider_name": "ollama",
            "provider_config": {
                "endpoint": "http://localhost:11434",
                "model": "llama3.2",
            },
        },
    )
    brain = AIBrain(project_dir)
    await brain.ensure_provider()

    result = await brain.start_provider()
    assert "already running" in result


async def test_start_provider_from_config(project_dir):
    """Starting loads provider from saved config."""
    save_config(
        project_dir,
        {
            "provider_name": "ollama",
            "provider_config": {
                "endpoint": "http://localhost:11434",
                "model": "llama3.2",
            },
        },
    )
    brain = AIBrain(project_dir)

    result = await brain.start_provider()

    assert "started" in result
    assert brain.provider is not None


async def test_start_provider_no_config(project_dir):
    """Starting with no config and no providers returns no provider."""
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="test", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        result = await brain.start_provider()

    assert result == AI_MSG.NO_PROVIDER


# ─── swap_provider ───────────────────────────────────────


async def test_swap_unknown_provider(project_dir):
    """Swapping to unknown provider returns error."""
    brain = AIBrain(project_dir)
    result = await brain.swap_provider("nonexistent")
    assert "unknown provider" in result


async def test_swap_to_ollama(project_dir):
    """Swap from nothing to ollama."""
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(
        available=True,
        models=["llama3.2"],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )

    with patch.object(
        _PROVIDER_MAP["ollama"][0], "discover", new=AsyncMock(return_value=mock_result)
    ):
        result = await brain.swap_provider("ollama")

    assert "swapped to ollama" in result
    assert brain.provider is not None
    assert brain.swapping is False

    # Config should be saved
    config = load_config(project_dir)
    assert config["provider_name"] == "ollama"


async def test_swap_stops_current_provider(project_dir):
    """Swapping stops the current provider first."""
    brain = AIBrain(project_dir)
    mock_old = MagicMock()
    mock_old.stop = MagicMock()
    brain._provider = mock_old

    mock_result = DiscoverResult(
        available=True,
        models=["llama3.2"],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )

    with patch.object(
        _PROVIDER_MAP["ollama"][0], "discover", new=AsyncMock(return_value=mock_result)
    ):
        await brain.swap_provider("ollama")

    mock_old.stop.assert_called_once()


async def test_swap_unavailable_provider(project_dir):
    """Swapping to unavailable provider returns error."""
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(
        available=False,
        provider_name="ollama",
        error="connection refused",
    )

    with patch.object(
        _PROVIDER_MAP["ollama"][0], "discover", new=AsyncMock(return_value=mock_result)
    ):
        result = await brain.swap_provider("ollama")

    assert "swap failed" in result
    assert brain.swapping is False


async def test_swap_with_specific_model(project_dir):
    """Swap with explicit model name."""
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(
        available=True,
        models=["llama3.2", "qwen2.5"],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )

    with patch.object(
        _PROVIDER_MAP["ollama"][0], "discover", new=AsyncMock(return_value=mock_result)
    ):
        result = await brain.swap_provider("ollama", model="qwen2.5")

    assert "qwen2.5" in result
    config = load_config(project_dir)
    assert config["provider_config"]["model"] == "qwen2.5"


# ─── configure ───────────────────────────────────────────


async def test_configure_clears_config(project_dir):
    """Configure clears saved config and provider."""
    save_config(
        project_dir,
        {
            "provider_name": "ollama",
            "provider_config": {
                "endpoint": "http://localhost:11434",
                "model": "llama3.2",
            },
        },
    )
    brain = AIBrain(project_dir)
    await brain.ensure_provider()
    assert brain._provider is not None

    result = await brain.configure()

    # Config cleared, no auto-discover
    assert brain._provider is None
    config = load_config(project_dir)
    assert config == {}
    assert "failed" in result


async def test_configure_no_provider_found(project_dir):
    """Configure with no providers available returns failure."""
    brain = AIBrain(project_dir)

    mock_result = DiscoverResult(available=False, provider_name="test", error="nope")
    with patch(
        "core.ai.brain._PROVIDERS",
        [(MagicMock(discover=AsyncMock(return_value=mock_result)), None)],
    ):
        result = await brain.configure()

    assert "failed" in result


# ─── respond during swap ─────────────────────────────────


async def test_respond_during_swap(project_dir):
    """Respond returns provider changing message during swap."""
    brain = AIBrain(project_dir)
    brain._swapping = True

    printed = []
    result = await brain.respond("hello", print_fn=lambda t: printed.append(t))

    assert result == AI_MSG.PROVIDER_CHANGING
    assert printed == [AI_MSG.PROVIDER_CHANGING]


# ─── available_providers ─────────────────────────────────


def test_available_providers():
    providers = AIBrain.available_providers()
    assert "ollama" in providers
    assert "integrated" in providers


# ─── config routing: integrated ──────────────────


async def test_provider_from_config_integrated(project_dir):
    """Brain loads integrated from config."""
    save_config(
        project_dir,
        {
            "provider_name": "integrated",
            "provider_config": {
                "endpoint": "local:cpu",
                "model": "Qwen/Qwen3.5-4B",
            },
        },
    )
    brain = AIBrain(project_dir)
    provider = await brain.ensure_provider()

    assert provider is not None
    assert provider.model == "Qwen/Qwen3.5-4B"
