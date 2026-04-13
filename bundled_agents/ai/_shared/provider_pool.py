"""Per-agent provider instance cache. One pool per AI bundle."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ProviderPool:
    """Caches provider instances keyed by agent_id.

    `factory` is a callable that takes an agent dict and returns a provider instance.
    `release` can be called to tear down (e.g. via engine.store.on_agent_deleted).
    """

    def __init__(self, factory: Callable[[dict], Any]):
        self._factory = factory
        self._providers: dict[str, Any] = {}

    def get_or_create(self, agent_id: str, agent: dict) -> Any:
        if agent_id not in self._providers:
            self._providers[agent_id] = self._factory(agent)
        return self._providers[agent_id]

    def get(self, agent_id: str) -> Any | None:
        return self._providers.get(agent_id)

    def release(self, agent_id: str) -> None:
        """Remove agent's provider — calls provider.unload() or .stop() for cleanup."""
        provider = self._providers.pop(agent_id, None)
        if provider is None:
            return
        for method in ("unload", "stop"):
            fn = getattr(provider, method, None)
            if callable(fn):
                try:
                    fn()
                except Exception as e:
                    logger.warning("Provider.%s failed for %s: %s", method, agent_id, e)
                break

    def clear(self) -> None:
        for aid in list(self._providers.keys()):
            self.release(aid)
