"""ProxyProvider — forwards generate() calls to a remote Fantastic instance.

Usage: ai_swap provider=proxy instance=<instance_id_or_name>
The instance must be registered first (launch_instance / register_instance).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import httpx

from ..provider import DiscoverResult, GenerationResult

logger = logging.getLogger(__name__)

# Timeout for generation (model inference can be slow)
_GENERATE_TIMEOUT = 300.0
_DEFAULT_TIMEOUT = 15.0


def resolve_instance(instance: str) -> str | None:
    """Resolve an instance ID or name to its URL from the instance registry.

    Returns the URL or None if not found / not running.
    """
    from ..tools._instance_tracking import _instance_list_sync

    for inst in _instance_list_sync():
        if inst["id"] == instance or inst.get("name") == instance:
            if inst["status"] == "running" and inst.get("url"):
                return inst["url"]
            return None
    return None


class ProxyProvider:
    """Stateless proxy that forwards inference to a remote Fantastic server.

    The remote instance runs its own provider (integrated, ollama, etc.).
    This provider just ships messages over HTTP and returns the result.
    Endpoint is resolved from the instance registry, not specified as raw URL.
    """

    def __init__(self, endpoint: str, model: str = "", instance: str = ""):
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._instance = instance

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult:
        """Probe a remote Fantastic instance for AI availability.

        endpoint can be a URL (from config) or an instance ID/name.
        """
        if not endpoint:
            return DiscoverResult(
                available=False,
                provider_name="proxy",
                error="no endpoint specified — use: ai_swap provider=proxy instance=<id>",
            )

        # If it looks like a URL, use it directly; otherwise resolve from registry
        if endpoint.startswith("http"):
            url = endpoint.rstrip("/")
        else:
            # Treat as instance ID or name
            url = resolve_instance(endpoint)
            if not url:
                return DiscoverResult(
                    available=False,
                    provider_name="proxy",
                    error=f"instance '{endpoint}' not found or not running",
                )

        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(
                    f"{url}/api/call",
                    json={"tool": "ai_status", "args": {}},
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("connected"):
                    return DiscoverResult(
                        available=False,
                        provider_name="proxy",
                        endpoint=url,
                        error="remote instance has no active AI provider",
                    )

                resp2 = await client.post(
                    f"{url}/api/call",
                    json={"tool": "ai_models", "args": {}},
                )
                resp2.raise_for_status()
                models = resp2.json().get("models", [])

                return DiscoverResult(
                    available=True,
                    models=models,
                    endpoint=url,
                    provider_name="proxy",
                )

        except Exception as e:
            return DiscoverResult(
                available=False,
                provider_name="proxy",
                endpoint=url,
                error=str(e),
            )

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]:
        """Forward messages to remote instance, yield the response."""
        try:
            async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._endpoint}/api/call",
                    json={
                        "tool": "ai_generate",
                        "args": {"messages": messages},
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                text = data.get("text", "")
                if text:
                    yield text
                elif data.get("error"):
                    yield f"[proxy error: {data['error']}]"

        except httpx.TimeoutException:
            yield "[proxy timeout — remote generation took too long]"
        except Exception as e:
            yield f"[proxy error: {e}]"

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]:
        """Proxy delegates to generate() — remote handles its own tool calling."""
        text_parts = []
        async for token in self.generate(messages):
            text_parts.append(token)
            yield token
        yield GenerationResult(text="".join(text_parts), tool_calls=None)

    async def list_models(self) -> list[str]:
        """List models available on the remote instance."""
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._endpoint}/api/call",
                    json={"tool": "ai_models", "args": {}},
                )
                resp.raise_for_status()
                return resp.json().get("models", [])
        except Exception as e:
            logger.warning(f"proxy list_models failed: {e}")
            return []

    async def pull(self, model: str) -> AsyncIterator[str]:
        """Pull a model on the remote instance."""
        try:
            async with httpx.AsyncClient(timeout=_GENERATE_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._endpoint}/api/call",
                    json={"tool": "ai_pull", "args": {"model": model}},
                )
                resp.raise_for_status()
                data = resp.json()
                yield data.get("status", f"pulled {model} on remote")
        except Exception as e:
            yield f"[proxy pull failed: {e}]"

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    def stop(self) -> None:
        pass

    def unload(self) -> None:
        pass
