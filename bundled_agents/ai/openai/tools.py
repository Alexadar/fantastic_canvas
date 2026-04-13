"""OpenAI-compatible AI agent bundle."""

from __future__ import annotations

import logging

from bundled_agents.ai._shared.ai_dispatch import AiBundleRuntime
from bundled_agents.ai.openai.provider import OpenAICompatibleProvider, DEFAULT_ENDPOINT

logger = logging.getLogger(__name__)

NAME = "openai"


def _provider_factory(agent: dict):
    endpoint = agent.get("endpoint") or DEFAULT_ENDPOINT
    model = agent.get("model") or ""
    api_key = agent.get("api_key", "")
    ctx_len = agent.get("context_length", 0)
    return OpenAICompatibleProvider(
        endpoint=endpoint, model=model, api_key=api_key, context_length=ctx_len
    )


_runtime = AiBundleRuntime(NAME, _provider_factory)


def register_dispatch() -> dict:
    return _runtime.make_dispatch_handlers()


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    from core.bus import bus as _bus

    _runtime.register(engine, _bus.broadcast)
    return {}


# Module-level CLI entry point — used by core input loop for @{agent_id} <text>
cli_sync = _runtime.cli_sync
