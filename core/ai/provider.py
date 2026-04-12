"""AIProvider protocol — the abstraction all providers implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class GenerationResult:
    """Result from a single generation round (may include tool calls)."""

    text: str
    tool_calls: list[dict] | None = None  # [{"name": ..., "arguments": {...}}]


@dataclass
class DiscoverResult:
    """Result of probing a provider endpoint."""

    available: bool
    models: list[str] = field(default_factory=list)
    endpoint: str = ""
    provider_name: str = ""
    error: str | None = None
    detail: str | None = None
    context_length: int = 0  # 0 = unknown


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

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]:
        """Stream tokens, then yield GenerationResult with tool_calls if any."""
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

    @property
    def context_length(self) -> int:
        """Max context window in tokens. 0 = unknown."""
        ...

    def set_model(self, model: str) -> None:
        """Switch to a different model."""
        ...

    def unload(self) -> None:
        """Unload resources (model, connections). Noop by default."""
        ...
