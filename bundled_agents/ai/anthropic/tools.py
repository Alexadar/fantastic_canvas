"""Anthropic Claude AI agent bundle."""

from __future__ import annotations

import logging

from bundled_agents.ai._shared.ai_dispatch import AiBundleRuntime
from bundled_agents.ai.anthropic.provider import AnthropicProvider, DEFAULT_MODEL

logger = logging.getLogger(__name__)

NAME = "anthropic"


def _provider_factory(agent: dict):
    model = agent.get("model") or DEFAULT_MODEL
    api_key = agent.get("api_key", "")
    return AnthropicProvider(model=model, api_key=api_key)


_runtime = AiBundleRuntime(NAME, _provider_factory)


def register_dispatch() -> dict:
    return _runtime.make_dispatch_handlers()


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    from core.bus import bus as _bus

    _runtime.register(engine, _bus.broadcast)
    return {}
