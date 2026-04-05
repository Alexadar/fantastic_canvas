"""Tests for AIBrain lock + epoch — concurrency guards and force-swap."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from core.ai.brain import AIBrain, _PROVIDER_MAP
from core.ai.config import save_config
from core.ai.messages import AI_MSG
from core.ai.provider import DiscoverResult
from core import conversation


def setup_function():
    conversation.clear()


def _make_brain(project_dir):
    save_config(
        project_dir,
        {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "llama3.2",
        },
    )
    return AIBrain(project_dir)


# ─── epoch basics ────────────────────────────────────────


async def test_epoch_starts_at_zero(project_dir):
    brain = AIBrain(project_dir)
    assert brain.generation_epoch == 0


async def test_stop_bumps_epoch(project_dir):
    brain = _make_brain(project_dir)
    await brain.ensure_provider()
    epoch_before = brain.generation_epoch

    await brain.stop_provider()

    assert brain.generation_epoch == epoch_before + 1


async def test_swap_bumps_epoch(project_dir):
    brain = _make_brain(project_dir)
    epoch_before = brain.generation_epoch

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

    assert brain.generation_epoch == epoch_before + 1


async def test_configure_bumps_epoch(project_dir):
    brain = _make_brain(project_dir)
    epoch_before = brain.generation_epoch

    mock_result = DiscoverResult(
        available=True,
        models=["llama3.2"],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )
    mock_cls = MagicMock()
    mock_cls.discover = AsyncMock(return_value=mock_result)
    mock_cls.return_value = MagicMock(model="llama3.2")

    with patch("core.ai.brain._PROVIDERS") as mock_providers:
        mock_providers.__iter__ = lambda self: iter(
            [(mock_cls, "http://localhost:11434")]
        )
        await brain.configure()

    assert brain.generation_epoch > epoch_before


# ─── generate respects epoch ─────────────────────────────


async def test_generate_yields_tokens(project_dir):
    brain = _make_brain(project_dir)

    async def mock_gen(messages):
        yield "Hello"
        yield " world"

    provider = await brain.ensure_provider()
    provider.generate = mock_gen

    tokens = []
    async for token in brain.generate([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    assert tokens == ["Hello", " world"]


async def test_generate_returns_changing_when_swapping(project_dir):
    brain = _make_brain(project_dir)
    brain._swapping = True

    tokens = []
    async for token in brain.generate([{"role": "user", "content": "hi"}]):
        tokens.append(token)

    assert tokens == [AI_MSG.PROVIDER_CHANGING]


# ─── force swap interrupts generation ────────────────────


async def test_force_swap_interrupts_generation(project_dir):
    """A force swap bumps epoch before lock, causing in-flight generate to abort."""
    brain = _make_brain(project_dir)

    # Slow generator that yields a few tokens then awaits
    generation_started = asyncio.Event()
    swap_done = asyncio.Event()

    async def slow_gen(messages):
        yield "tok1"
        generation_started.set()
        # Wait a bit to simulate slow inference — the force swap will
        # bump epoch while we're here
        await swap_done.wait()
        yield "tok2_should_not_appear"

    provider = await brain.ensure_provider()
    provider.generate = slow_gen

    tokens = []
    generation_complete = asyncio.Event()

    async def run_generate():
        async for token in brain.generate([{"role": "user", "content": "hi"}]):
            tokens.append(token)
        generation_complete.set()

    async def run_force_swap():
        await generation_started.wait()
        # Force bump epoch — this happens before acquiring lock
        brain._generation_epoch += 1
        brain._swapping = True
        swap_done.set()

    await asyncio.gather(run_generate(), run_force_swap())

    # First token was yielded before the force swap
    assert "tok1" in tokens
    # Generation was interrupted
    assert AI_MSG.PROVIDER_CHANGING in tokens
    # The post-swap token should NOT appear
    assert "tok2_should_not_appear" not in tokens


async def test_force_stop_bumps_epoch_immediately(project_dir):
    """force=True bumps epoch before acquiring lock."""
    brain = _make_brain(project_dir)
    await brain.ensure_provider()

    epoch_before = brain.generation_epoch
    # Simulate the lock being held by acquiring it
    await brain._lock.acquire()

    async def do_stop():
        return await brain.stop_provider(force=True)

    # Force stop should bump epoch immediately (before lock)
    # We check epoch is bumped even though lock is held
    stop_task = asyncio.create_task(do_stop())
    await asyncio.sleep(0)  # let task start

    assert brain.generation_epoch == epoch_before + 1

    # Release lock so stop can complete
    brain._lock.release()
    result = await stop_task
    assert "stopped" in result


async def test_normal_swap_waits_for_generation(project_dir):
    """Non-force swap waits for the lock (i.e., waits for generation to finish)."""
    brain = _make_brain(project_dir)

    lock_acquired = asyncio.Event()
    release = asyncio.Event()

    async def hold_lock():
        async with brain._lock:
            lock_acquired.set()
            await release.wait()

    mock_result = DiscoverResult(
        available=True,
        models=["llama3.2"],
        endpoint="http://localhost:11434",
        provider_name="ollama",
    )

    holder = asyncio.create_task(hold_lock())
    await lock_acquired.wait()

    swap_started = False
    swap_result = None

    async def do_swap():
        nonlocal swap_started, swap_result
        swap_started = True
        with patch.object(
            _PROVIDER_MAP["ollama"][0],
            "discover",
            new=AsyncMock(return_value=mock_result),
        ):
            swap_result = await brain.swap_provider("ollama")

    swap_task = asyncio.create_task(do_swap())
    await asyncio.sleep(0)  # let swap task start

    # Swap should be blocked by the lock
    assert swap_started
    assert swap_result is None

    # Release — swap proceeds
    release.set()
    await holder
    await swap_task

    assert swap_result is not None
    assert "swapped" in swap_result


# ─── respond uses generate ───────────────────────────────


async def test_respond_uses_generate_with_lock(project_dir):
    """respond() goes through generate() which holds the lock."""
    brain = _make_brain(project_dir)

    from core.ai.provider import GenerationResult

    async def mock_gen_with_tools(messages, tools):
        yield "Hello"
        yield GenerationResult(text="Hello", tool_calls=None)

    provider = await brain.ensure_provider()
    provider.generate_with_tools = mock_gen_with_tools

    printed = []
    response = await brain.respond("hi", print_fn=lambda t: printed.append(t))

    assert response == "Hello"
    assert printed == ["Hello"]


async def test_respond_interrupted_by_force_swap(project_dir):
    """respond() returns PROVIDER_CHANGING when force swap bumps epoch mid-generation."""
    brain = _make_brain(project_dir)
    from core.ai.provider import GenerationResult

    async def mock_gen_with_tools(messages, tools):
        # Bump epoch mid-generation to simulate force swap
        brain._generation_epoch += 1
        yield GenerationResult(
            text="", tool_calls=[{"name": "list_agents", "arguments": {}}]
        )

    provider = await brain.ensure_provider()
    provider.generate_with_tools = mock_gen_with_tools

    printed = []
    result = await brain.respond("hi", print_fn=lambda t: printed.append(t))

    assert result == AI_MSG.PROVIDER_CHANGING
