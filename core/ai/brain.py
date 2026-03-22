"""AIBrain — reads conversation buffer, streams from provider, writes response back."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator, Callable

from .. import conversation
from .config import load_config, save_config
from .messages import AI_MSG
from .provider import AIProvider, DiscoverResult

logger = logging.getLogger(__name__)

# Registered providers: (class, default_endpoint)
_PROVIDERS: list[tuple[type, str | None]] = []

# Map of provider_name → (class, default_endpoint) for swap lookups
_PROVIDER_MAP: dict[str, tuple[type, str | None]] = {}


def register_provider(cls: type, default_endpoint: str | None = None) -> None:
    """Register a provider class for auto-discovery."""
    _PROVIDERS.append((cls, default_endpoint))


# Register integrated first (default), then Ollama as fallback
from .integrated_provider import IntegratedProvider
register_provider(IntegratedProvider, None)

from .ollama_provider import OllamaProvider, DEFAULT_ENDPOINT
register_provider(OllamaProvider, DEFAULT_ENDPOINT)

from .proxy_provider import ProxyProvider

_PROVIDER_MAP["integrated"] = (IntegratedProvider, None)
_PROVIDER_MAP["ollama"] = (OllamaProvider, DEFAULT_ENDPOINT)
_PROVIDER_MAP["proxy"] = (ProxyProvider, None)


class AIBrain:
    """Reads conversation, builds messages, streams from provider."""

    def __init__(self, project_dir: Path):
        self._project_dir = project_dir
        self._provider: AIProvider | None = None
        self._say: Callable[[str, str], dict] = conversation.say
        self._swapping = False
        self._lock = asyncio.Lock()
        self._generation_epoch = 0

    @property
    def provider(self) -> AIProvider | None:
        return self._provider

    @property
    def swapping(self) -> bool:
        return self._swapping

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
        if name == "integrated":
            return IntegratedProvider(
                model=config.get("model", ""),
            )
        if name == "proxy":
            # Re-resolve instance URL (tunnel port may have changed)
            instance = config.get("instance", "")
            endpoint = config.get("endpoint", "")
            if instance:
                from .proxy_provider import resolve_instance
                resolved = resolve_instance(instance)
                if resolved:
                    endpoint = resolved
            if not endpoint:
                return None
            return ProxyProvider(
                endpoint=endpoint,
                model=config.get("model", ""),
                instance=instance,
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

                # Instantiate — integrated takes model only
                if result.provider_name == "integrated":
                    self._provider = cls(model=model)
                else:
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

        self._say_ai("no AI provider found. Install torch+transformers or Ollama.")
        return None

    @property
    def generation_epoch(self) -> int:
        return self._generation_epoch

    # Sentinel: generate() yields this when no provider is available.
    # Callers compare by identity (``is``) to distinguish from real tokens.
    NO_PROVIDER_SENTINEL = object()

    async def generate(self, messages: list[dict]) -> AsyncIterator[str | object]:
        """Run inference with lock + epoch guard. Yields tokens.

        If a force-swap bumps the epoch mid-generation, iteration aborts
        and yields PROVIDER_CHANGING so the caller knows to stop.
        If no provider is available, yields NO_PROVIDER_SENTINEL once.
        """
        if self._swapping:
            yield AI_MSG.PROVIDER_CHANGING
            return

        epoch = self._generation_epoch

        async with self._lock:
            # Re-check after acquiring lock
            if self._swapping or epoch != self._generation_epoch:
                yield AI_MSG.PROVIDER_CHANGING
                return

            provider = await self.ensure_provider()
            if not provider:
                yield self.NO_PROVIDER_SENTINEL
                return

            async for token in provider.generate(messages):
                # Epoch changed — a force swap interrupted us
                if self._generation_epoch != epoch:
                    yield AI_MSG.PROVIDER_CHANGING
                    return
                yield token

    async def respond(self, user_text: str, print_fn: Callable[[str], None] | None = None) -> str | None:
        """Handle user input: build messages from conversation, stream response."""
        messages = self._build_messages(user_text)

        chunks: list[str] = []
        async for token in self.generate(messages):
            if token is self.NO_PROVIDER_SENTINEL:
                return None
            if token == AI_MSG.PROVIDER_CHANGING:
                if print_fn:
                    print_fn(AI_MSG.PROVIDER_CHANGING)
                return AI_MSG.PROVIDER_CHANGING
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

    async def stop_provider(self, force: bool = False) -> str:
        """Stop current provider, free resources (VRAM etc).

        If force=True, bumps epoch immediately (interrupts in-flight generations)
        then acquires lock. Otherwise waits for in-flight generations to finish.
        """
        if self._provider is None:
            return AI_MSG.NO_PROVIDER

        if force:
            self._generation_epoch += 1

        async with self._lock:
            if self._provider is None:
                return AI_MSG.NO_PROVIDER

            provider_name = self._get_provider_name()

            if hasattr(self._provider, "stop"):
                self._provider.stop()

            self._provider = None
            if not force:
                self._generation_epoch += 1
            self._say_ai(f"{AI_MSG.PROVIDER_STOPPED}: {provider_name}")
            return f"stopped {provider_name}"

    async def start_provider(self) -> str:
        """Start (or restart) provider from saved config or auto-discover."""
        async with self._lock:
            if self._provider is not None:
                return f"already running: {self._get_provider_name()}"

            self._say_ai(AI_MSG.PROVIDER_STARTING)
            provider = await self.ensure_provider()
            if provider is None:
                return AI_MSG.NO_PROVIDER
            name = self._get_provider_name()
            self._say_ai(f"{AI_MSG.MODEL_READY}: {name}")
            return f"started {name}"

    async def configure(self) -> str:
        """Reconfigure: stop current provider, clear config, re-discover."""
        self._generation_epoch += 1

        async with self._lock:
            if self._provider is not None:
                if hasattr(self._provider, "stop"):
                    self._provider.stop()
                self._provider = None

            save_config(self._project_dir, {})
            self._say_ai(AI_MSG.PROVIDER_CHANGING)

            provider = await self._auto_discover()
            if provider:
                name = self._get_provider_name()
                return f"reconfigured: {name}"
            return "reconfigure failed — no provider found"

    async def swap_provider(self, target: str, model: str | None = None,
                            instance: str | None = None,
                            force: bool = False) -> str:
        """Hot-swap to a different provider. Returns status string.

        If force=True, bumps epoch immediately so in-flight generations see
        PROVIDER_CHANGING at their next yield, then acquires the lock.
        Otherwise waits for in-flight generations to finish first.

        For proxy provider, ``instance`` is required (instance ID or name).
        """
        if target not in _PROVIDER_MAP:
            available = ", ".join(_PROVIDER_MAP.keys())
            return f"unknown provider '{target}'. available: {available}"

        if target == "proxy" and not instance:
            return "proxy requires instance= (registered instance ID or name)"

        # Force: bump epoch before lock — interrupts in-flight generations
        if force:
            self._generation_epoch += 1

        self._swapping = True
        try:
            async with self._lock:
                # Stop current provider
                if self._provider is not None:
                    if hasattr(self._provider, "stop"):
                        self._provider.stop()
                    self._provider = None

                cls, default_endpoint = _PROVIDER_MAP[target]
                discover_endpoint = instance if target == "proxy" else default_endpoint

                result = await cls.discover(discover_endpoint)
                if not result.available:
                    err = result.error or "not available"
                    self._say_ai(f"swap failed: {target} — {err}")
                    return f"swap failed: {err}"

                chosen_model = model or (result.models[0] if result.models else "")
                if not chosen_model:
                    self._say_ai(f"{target} available but no models")
                    return f"{target} available but no models"

                if target == "integrated":
                    self._provider = cls(model=chosen_model)
                elif target == "proxy":
                    self._provider = cls(
                        endpoint=result.endpoint, model=chosen_model,
                        instance=instance,
                    )
                else:
                    self._provider = cls(endpoint=result.endpoint, model=chosen_model)

                config = {
                    "provider": target,
                    "endpoint": result.endpoint,
                    "model": chosen_model,
                }
                if instance:
                    config["instance"] = instance
                save_config(self._project_dir, config)

                # Bump epoch if we didn't force (normal swap still invalidates old generations)
                if not force:
                    self._generation_epoch += 1

                self._say_ai(f"swapped to {target} ({chosen_model})")
                return f"swapped to {target} ({chosen_model})"
        finally:
            self._swapping = False

    def _get_provider_name(self) -> str:
        """Get the name of the current provider from config or class name."""
        config = load_config(self._project_dir)
        if config:
            return config.get("provider", "unknown")
        return type(self._provider).__name__ if self._provider else "unknown"

    @staticmethod
    def available_providers() -> list[str]:
        """Return list of registered provider names."""
        return list(_PROVIDER_MAP.keys())
