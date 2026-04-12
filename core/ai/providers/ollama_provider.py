"""OllamaProvider — first AIProvider implementation."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from ..provider import DiscoverResult, GenerationResult

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://localhost:11434"


class OllamaProvider:
    """Wraps ollama.AsyncClient to implement AIProvider."""

    def __init__(self, endpoint: str, model: str, context_length: int = 0):
        self._endpoint = endpoint
        self._model = model
        self._context_length = context_length
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
            # Try to get context length from first model
            ctx_len = 0
            if models:
                try:
                    info = await client.show(models[0])
                    params = getattr(info, "model_info", {}) or {}
                    if isinstance(params, dict):
                        for k, v in params.items():
                            if "context_length" in k:
                                ctx_len = int(v)
                                break
                except Exception:
                    pass
            return DiscoverResult(
                available=True,
                models=models,
                endpoint=ep,
                provider_name="ollama",
                context_length=ctx_len,
            )
        except ImportError:
            return DiscoverResult(
                available=False,
                provider_name="ollama",
                error="ollama package not installed. Run: uv pip install ollama",
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

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]:
        """Stream tokens, then yield GenerationResult with tool_calls if any."""
        client = self._get_client()
        stream = await client.chat(
            model=self._model,
            messages=messages,
            tools=tools,
            stream=True,
        )
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        async for chunk in stream:
            msg = chunk.get("message", {})
            content = msg.get("content", "")
            if content:
                text_parts.append(content)
                yield content
            calls = msg.get("tool_calls")
            if calls:
                for c in calls:
                    fn = c.get("function", {})
                    tool_calls.append(
                        {
                            "name": fn.get("name", ""),
                            "arguments": fn.get("arguments", {}),
                        }
                    )
        yield GenerationResult(
            text="".join(text_parts),
            tool_calls=tool_calls or None,
        )

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

    @property
    def context_length(self) -> int:
        return self._context_length

    def set_model(self, model: str) -> None:
        self._model = model

    def __str__(self) -> str:
        return f"ollama ({self._model})"

    def stop(self) -> None:
        self._client = None

    def unload(self) -> None:
        self.stop()
