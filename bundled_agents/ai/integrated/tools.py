"""Integrated (local torch+transformers) AI agent bundle.

on_delete hook unloads model from VRAM.
"""

from __future__ import annotations

import logging

from bundled_agents.ai._shared.ai_dispatch import AiBundleRuntime
from bundled_agents.ai.integrated.provider import IntegratedProvider

logger = logging.getLogger(__name__)

NAME = "integrated"


def _provider_factory(agent: dict):
    model = agent.get("model") or ""
    return IntegratedProvider(model=model)


_runtime = AiBundleRuntime(NAME, _provider_factory)


def register_dispatch() -> dict:
    return _runtime.make_dispatch_handlers()


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    from core.bus import bus as _bus

    _runtime.register(engine, _bus.broadcast)
    # on_delete is registered by AiBundleRuntime.register() via pool.release
    # which calls provider.unload() → clears torch model from VRAM
    return {}


# Module-level CLI entry point — used by core input loop for @{agent_id} <text>
cli_sync = _runtime.cli_sync
