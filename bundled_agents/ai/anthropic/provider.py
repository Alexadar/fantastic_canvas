"""AnthropicProvider — Claude API via the anthropic SDK."""

from __future__ import annotations

import logging
import os
from typing import AsyncIterator

from bundled_agents.ai._shared.provider_protocol import DiscoverResult, GenerationResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicProvider:
    """Streams completions from the Anthropic Messages API."""

    # Claude models all support 200k context
    _CONTEXT_LENGTHS: dict[str, int] = {
        "claude-opus-4": 200000,
        "claude-sonnet-4": 200000,
        "claude-haiku-4": 200000,
    }

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str = ""):
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    @classmethod
    async def discover(cls, endpoint: str | None = None) -> DiscoverResult:
        """Check if anthropic SDK is installed and API key is available."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return DiscoverResult(
                available=False,
                provider_name="anthropic",
                error="anthropic package not installed. Run: uv pip install anthropic",
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return DiscoverResult(
                available=False,
                provider_name="anthropic",
                error="ANTHROPIC_API_KEY not set",
            )

        # Verify key by listing models
        try:
            client = anthropic.AsyncAnthropic(api_key=api_key)
            models = await _list_models(client)
            return DiscoverResult(
                available=True,
                models=models or [DEFAULT_MODEL],
                endpoint="https://api.anthropic.com",
                provider_name="anthropic",
            )
        except Exception as e:
            return DiscoverResult(
                available=False,
                provider_name="anthropic",
                error=str(e),
            )

    async def generate(self, messages: list[dict]) -> AsyncIterator[str]:
        """Stream completion tokens from Claude."""
        client = self._get_client()

        # Separate system message from the rest
        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": chat_messages,
        }
        if system_text:
            kwargs["system"] = system_text

        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def generate_with_tools(
        self, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[str | GenerationResult]:
        """Stream tokens with tool calling support via Anthropic API."""
        client = self._get_client()

        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            elif msg["role"] == "tool":
                # Anthropic uses tool_result blocks
                chat_messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_use_id", ""),
                                "content": msg["content"],
                            }
                        ],
                    }
                )
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        # Convert tool format from Ollama/OpenAI → Anthropic
        anthropic_tools = []
        for t in tools:
            fn = t.get("function", {})
            anthropic_tools.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get(
                        "parameters", {"type": "object", "properties": {}}
                    ),
                }
            )

        kwargs: dict = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": chat_messages,
            "tools": anthropic_tools,
        }
        if system_text:
            kwargs["system"] = system_text

        response = await client.messages.create(**kwargs)

        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
                yield block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    {
                        "name": block.name,
                        "arguments": block.input,
                        "tool_use_id": block.id,
                    }
                )

        yield GenerationResult(
            text="".join(text_parts),
            tool_calls=tool_calls or None,
        )

    async def list_models(self) -> list[str]:
        """List available Claude models."""
        client = self._get_client()
        return await _list_models(client)

    async def pull(self, model: str) -> AsyncIterator[str]:
        """No-op for API provider — model is always available."""
        self._model = model
        yield f"model set to {model} (API — no download needed)"

    @property
    def model(self) -> str:
        return self._model

    @property
    def context_length(self) -> int:
        for prefix, ctx in self._CONTEXT_LENGTHS.items():
            if self._model.startswith(prefix):
                return ctx
        return 200000  # safe default for Claude models

    def set_model(self, model: str) -> None:
        self._model = model

    def __str__(self) -> str:
        return f"anthropic ({self._model})"

    def stop(self) -> None:
        self._client = None

    def unload(self) -> None:
        self.stop()


async def _list_models(client) -> list[str]:
    """Fetch model list from the API. Returns IDs sorted newest-first."""
    try:
        page = await client.models.list(limit=100)
        return [m.id for m in page.data]
    except Exception:
        # Fallback — models.list may not be available on all plans
        return [DEFAULT_MODEL]
