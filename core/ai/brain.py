"""AIBrain — reads conversation buffer, streams from provider, writes response back."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from .. import conversation
from .config import load_config, save_config
from .provider import AIProvider, DiscoverResult

logger = logging.getLogger(__name__)

# Registered providers: (class, default_endpoint)
_PROVIDERS: list[tuple[type, str | None]] = []


def register_provider(cls: type, default_endpoint: str | None = None) -> None:
    """Register a provider class for auto-discovery."""
    _PROVIDERS.append((cls, default_endpoint))


# Register Ollama as first provider
from .ollama_provider import OllamaProvider, DEFAULT_ENDPOINT
register_provider(OllamaProvider, DEFAULT_ENDPOINT)


class AIBrain:
    """Reads conversation, builds messages, streams from provider."""

    def __init__(self, project_dir: Path):
        self._project_dir = project_dir
        self._provider: AIProvider | None = None
        self._say: Callable[[str, str], dict] = conversation.say

    @property
    def provider(self) -> AIProvider | None:
        return self._provider

    async def ensure_provider(self) -> AIProvider | None:
        """Load from config or auto-discover. Returns provider or None."""
        if self._provider:
            return self._provider

        # Try loading saved config
        config = load_config(self._project_dir)
        if config:
            provider = self._provider_from_config(config)
            if provider:
                self._provider = provider
                return provider

        # Auto-discover
        return await self._auto_discover()

    def _provider_from_config(self, config: dict) -> AIProvider | None:
        """Instantiate provider from saved config."""
        name = config.get("provider")
        if name == "ollama":
            return OllamaProvider(
                endpoint=config.get("endpoint", DEFAULT_ENDPOINT),
                model=config.get("model", ""),
            )
        return None

    async def _auto_discover(self) -> AIProvider | None:
        """Try each registered provider, first match wins."""
        for cls, default_endpoint in _PROVIDERS:
            result: DiscoverResult = await cls.discover(default_endpoint)

            if result.available and result.models:
                # Pick first model, save config
                model = result.models[0]
                config = {
                    "provider": result.provider_name,
                    "endpoint": result.endpoint,
                    "model": model,
                }
                save_config(self._project_dir, config)
                self._provider = cls(endpoint=result.endpoint, model=model)

                self._say_ai(f"auto-configured: {result.provider_name} ({model})")
                return self._provider

            if result.available and not result.models:
                self._say_ai(
                    f"{result.provider_name} running but no models. "
                    f"Run: ollama pull llama3.2"
                )
                return None

            if result.error:
                logger.debug(f"Provider {result.provider_name}: {result.error}")

        self._say_ai("no AI provider found. Install Ollama: https://ollama.ai")
        return None

    async def respond(self, user_text: str, print_fn: Callable[[str], None] | None = None) -> str | None:
        """Handle user input: build messages from conversation, stream response."""
        provider = await self.ensure_provider()
        if not provider:
            return None

        # Build messages from conversation buffer
        messages = self._build_messages(user_text)

        # Stream response
        chunks: list[str] = []
        async for token in provider.chat(messages):
            chunks.append(token)
            if print_fn:
                print_fn(token)

        response = "".join(chunks)
        if response:
            self._say_ai(response)
        return response

    def _build_messages(self, current_input: str) -> list[dict]:
        """Convert conversation buffer to chat messages."""
        messages: list[dict] = []

        # System message
        messages.append({
            "role": "system",
            "content": "You are a helpful AI assistant in the Fantastic Canvas environment.",
        })

        # Recent conversation history
        for entry in conversation.read(max_lines=50):
            who = entry["who"].lower()
            content = entry["message"]

            if who == "user":
                messages.append({"role": "user", "content": content})
            elif who == "ai":
                messages.append({"role": "assistant", "content": content})
            # Skip system/fantastic messages — they're internal

        # Current input (if not already in buffer)
        messages.append({"role": "user", "content": current_input})

        return messages

    def _say_ai(self, message: str) -> None:
        """Write AI message to conversation buffer."""
        self._say("ai", message)

    # ─── Direct commands ──────────────────────────────────────

    async def status(self) -> dict:
        """Return current AI status."""
        config = load_config(self._project_dir)
        provider = await self.ensure_provider()
        return {
            "configured": config is not None,
            "provider": config.get("provider") if config else None,
            "model": config.get("model") if config else None,
            "endpoint": config.get("endpoint") if config else None,
            "connected": provider is not None,
        }

    async def models(self) -> list[str]:
        """List available models from current provider."""
        provider = await self.ensure_provider()
        if not provider:
            return []
        return await provider.list_models()

    async def set_model(self, model: str) -> None:
        """Switch model and persist."""
        provider = await self.ensure_provider()
        if not provider:
            raise RuntimeError("No AI provider available")
        provider.set_model(model)
        config = load_config(self._project_dir) or {}
        config["model"] = model
        save_config(self._project_dir, config)
        self._say_ai(f"model set to {model}")

    async def pull_model(self, model: str, print_fn: Callable[[str], None] | None = None) -> None:
        """Pull a model from provider."""
        provider = await self.ensure_provider()
        if not provider:
            raise RuntimeError("No AI provider available")
        async for progress in provider.pull(model):
            if print_fn:
                print_fn(f"\r  {progress}")
        if print_fn:
            print_fn(f"\n  pulled {model}")
        self._say_ai(f"pulled model: {model}")
