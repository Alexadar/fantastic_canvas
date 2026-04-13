"""AI provider protocol — shared by all AI bundles."""

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
    """Protocol all AI providers implement (duck typing, no base class)."""

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult: ...

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]: ...

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]: ...

    async def list_models(self) -> list[str]: ...

    async def pull(self, model: str) -> AsyncIterator[str]: ...

    @property
    def model(self) -> str: ...

    @property
    def context_length(self) -> int: ...

    def set_model(self, model: str) -> None: ...

    def unload(self) -> None: ...
