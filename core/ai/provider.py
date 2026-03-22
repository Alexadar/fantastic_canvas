"""AIProvider protocol — the abstraction all providers implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class DiscoverResult:
    """Result of probing a provider endpoint."""
    available: bool
    models: list[str] = field(default_factory=list)
    endpoint: str = ""
    provider_name: str = ""
    error: str | None = None
    detail: str | None = None


@runtime_checkable
class AIProvider(Protocol):
    """Protocol that all AI providers must implement."""

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult:
        """Probe whether this provider is available at the given endpoint."""
        ...

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream completion tokens from messages."""
        ...

    async def list_models(self) -> list[str]:
        """Return available model names."""
        ...

    async def pull(self, model: str) -> AsyncIterator[str]:
        """Pull/download a model. Yields progress strings."""
        ...

    @property
    def model(self) -> str:
        """Current model name."""
        ...

    def set_model(self, model: str) -> None:
        """Switch to a different model."""
        ...
