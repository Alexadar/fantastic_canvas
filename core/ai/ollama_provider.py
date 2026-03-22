"""OllamaProvider — first AIProvider implementation."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from .provider import AIProvider, DiscoverResult

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://localhost:11434"


class OllamaProvider:
    """Wraps ollama.AsyncClient to implement AIProvider."""

    def __init__(self, endpoint: str, model: str):
        self._endpoint = endpoint
        self._model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import ollama
            self._client = ollama.AsyncClient(host=self._endpoint)
        return self._client

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult:
        """Probe Ollama at endpoint (default localhost:11434)."""
        ep = endpoint or DEFAULT_ENDPOINT
        try:
            import ollama
            client = ollama.AsyncClient(host=ep)
            resp = await client.list()
            models = [m.model for m in resp.models] if resp.models else []
            return DiscoverResult(
                available=True,
                models=models,
                endpoint=ep,
                provider_name="ollama",
            )
        except ImportError:
            return DiscoverResult(
                available=False,
                provider_name="ollama",
                error="ollama package not installed. Run: pip install ollama",
            )
        except Exception as e:
            return DiscoverResult(
                available=False,
                provider_name="ollama",
                endpoint=ep,
                error=str(e),
            )

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream completion tokens from Ollama."""
        client = self._get_client()
        stream = await client.chat(
            model=self._model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    async def list_models(self) -> list[str]:
        """List available models."""
        client = self._get_client()
        resp = await client.list()
        return [m.model for m in resp.models] if resp.models else []

    async def pull(self, model: str) -> AsyncIterator[str]:
        """Pull a model, yielding progress."""
        client = self._get_client()
        stream = await client.pull(model, stream=True)
        async for progress in stream:
            status = progress.get("status", "")
            total = progress.get("total", 0)
            completed = progress.get("completed", 0)
            if total:
                pct = int(completed / total * 100)
                yield f"{status} {pct}%"
            elif status:
                yield status

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model
