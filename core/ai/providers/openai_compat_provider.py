"""OpenAI-compatible provider — connects to any /v1/chat/completions endpoint.

Works with llama-cpp-server, vLLM, text-generation-inference, and OpenAI itself.
Uses httpx directly (no SDK dependency).
"""

from __future__ import annotations

import json
import logging
import os
from typing import AsyncIterator

import httpx

from ..provider import DiscoverResult, GenerationResult

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://localhost:8080/v1"
_GENERATE_TIMEOUT = 300.0
_DEFAULT_TIMEOUT = 15.0


async def _iter_sse(response: httpx.Response) -> AsyncIterator[dict]:
    """Parse SSE lines from an httpx streaming response into dicts."""
    async for line in response.aiter_lines():
        if not line or not line.startswith("data: "):
            continue
        payload = line[len("data: ") :]
        if payload.strip() == "[DONE]":
            return
        yield json.loads(payload)


class OpenAICompatibleProvider:
    """Connects to any OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(self, endpoint: str, model: str, api_key: str = "", context_length: int = 0):
        self._endpoint = endpoint.rstrip("/")
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._context_length = context_length
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                headers=headers, timeout=_DEFAULT_TIMEOUT
            )
        return self._client

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult:
        """Probe an OpenAI-compatible endpoint for available models."""
        ep = endpoint or DEFAULT_ENDPOINT
        ep = ep.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                resp = await client.get(f"{ep}/models")
                resp.raise_for_status()
                data = resp.json()
                models_data = data.get("data", [])
                models = [m["id"] for m in models_data]
                # Extract context length from first model's metadata
                ctx_len = 0
                if models_data:
                    meta = models_data[0].get("meta", {})
                    ctx_len = meta.get("n_ctx_train", 0)
                return DiscoverResult(
                    available=True,
                    models=models,
                    endpoint=ep,
                    provider_name="openai",
                    context_length=ctx_len,
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            return DiscoverResult(
                available=False,
                provider_name="openai",
                endpoint=ep,
                error=str(e),
            )
        except Exception as e:
            return DiscoverResult(
                available=False,
                provider_name="openai",
                endpoint=ep,
                error=str(e),
            )

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream completion tokens."""
        client = self._get_client()
        body = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        async with client.stream(
            "POST",
            f"{self._endpoint}/chat/completions",
            json=body,
            timeout=_GENERATE_TIMEOUT,
        ) as response:
            if response.status_code >= 400:
                body_bytes = await response.aread()
                raise RuntimeError(
                    f"OpenAI-compatible server error {response.status_code}: "
                    f"{body_bytes.decode(errors='replace')[:500]}"
                )
            async for chunk in _iter_sse(response):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content") or ""
                if content:
                    yield content

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]:
        """Stream tokens and accumulate tool calls."""
        client = self._get_client()
        body: dict = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            body["tools"] = tools

        text_parts: list[str] = []
        # Accumulate tool calls by index: {index: {"name": str, "arguments": str}}
        tc_map: dict[int, dict[str, str]] = {}

        async with client.stream(
            "POST",
            f"{self._endpoint}/chat/completions",
            json=body,
            timeout=_GENERATE_TIMEOUT,
        ) as response:
            if response.status_code >= 400:
                body_bytes = await response.aread()
                raise RuntimeError(
                    f"OpenAI-compatible server error {response.status_code}: "
                    f"{body_bytes.decode(errors='replace')[:500]}"
                )
            async for chunk in _iter_sse(response):
                delta = chunk.get("choices", [{}])[0].get("delta", {})

                content = delta.get("content") or ""
                if content:
                    text_parts.append(content)
                    yield content

                for tc in delta.get("tool_calls", []):
                    idx = tc.get("index", 0)
                    fn = tc.get("function", {})
                    if idx not in tc_map:
                        tc_map[idx] = {"name": fn.get("name", ""), "arguments": ""}
                    else:
                        if fn.get("name"):
                            tc_map[idx]["name"] = fn["name"]
                    tc_map[idx]["arguments"] += fn.get("arguments", "")

        # Build final tool_calls list
        tool_calls: list[dict] | None = None
        if tc_map:
            tool_calls = []
            for idx in sorted(tc_map):
                entry = tc_map[idx]
                try:
                    args = json.loads(entry["arguments"]) if entry["arguments"] else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"name": entry["name"], "arguments": args})

        yield GenerationResult(
            text="".join(text_parts),
            tool_calls=tool_calls,
        )

    async def list_models(self) -> list[str]:
        """List available models from the endpoint."""
        client = self._get_client()
        resp = await client.get(f"{self._endpoint}/models")
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", [])]

    async def pull(self, model: str) -> AsyncIterator[str]:
        """No-op — external servers manage their own models."""
        self._model = model
        yield f"model set to {model} (external server — no download needed)"

    @property
    def model(self) -> str:
        return self._model

    @property
    def context_length(self) -> int:
        return self._context_length

    def set_model(self, model: str) -> None:
        self._model = model

    def __str__(self) -> str:
        return f"openai ({self._model})"

    def stop(self) -> None:
        if self._client:
            # httpx.AsyncClient.aclose() is async; just drop the reference
            self._client = None

    def unload(self) -> None:
        self.stop()
