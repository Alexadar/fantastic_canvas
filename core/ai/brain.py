"""AIBrain — reads conversation buffer, streams from provider, writes response back."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import AsyncIterator, Callable

from .. import conversation
from .config import load_config, save_config
from .providers.integrated_provider import IntegratedProvider
from .messages import AI_MSG
from .providers.ollama_provider import OllamaProvider, DEFAULT_ENDPOINT
from .providers.anthropic_provider import AnthropicProvider
from .provider import AIProvider, GenerationResult
from .providers.proxy_provider import ProxyProvider
from .providers.openai_compat_provider import (
    OpenAICompatibleProvider,
    DEFAULT_ENDPOINT as DEFAULT_ENDPOINT_OPENAI,
)
from .tool_schema import build_ollama_tools

MAX_TOOL_ROUNDS = 20  # max agentic loop iterations per response

logger = logging.getLogger(__name__)

# Registered providers: (class, default_endpoint)
_PROVIDERS: list[tuple[type, str | None]] = []

# Map of provider_name → (class, default_endpoint) for swap lookups
_PROVIDER_MAP: dict[str, tuple[type, str | None]] = {}


def register_provider(cls: type, default_endpoint: str | None = None) -> None:
    """Register a provider class for auto-discovery."""
    _PROVIDERS.append((cls, default_endpoint))


# Register integrated first (default), then Ollama as fallback
register_provider(IntegratedProvider, None)
register_provider(OllamaProvider, DEFAULT_ENDPOINT)

_PROVIDER_MAP["integrated"] = (IntegratedProvider, None)
_PROVIDER_MAP["ollama"] = (OllamaProvider, DEFAULT_ENDPOINT)
_PROVIDER_MAP["proxy"] = (ProxyProvider, None)
_PROVIDER_MAP["anthropic"] = (AnthropicProvider, None)
_PROVIDER_MAP["openai"] = (OpenAICompatibleProvider, DEFAULT_ENDPOINT_OPENAI)


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
        name = config.get("provider_name")
        pc = config.get("provider_config", {})
        if name == "ollama":
            return OllamaProvider(
                endpoint=pc.get("endpoint", DEFAULT_ENDPOINT),
                model=pc.get("model", ""),
                context_length=pc.get("context_length", 0),
            )
        if name == "integrated":
            return IntegratedProvider(
                model=pc.get("model", ""),
            )
        if name == "proxy":
            instance = pc.get("instance", "")
            endpoint = pc.get("endpoint", "")
            if instance:
                from .providers.proxy_provider import resolve_instance

                resolved = resolve_instance(instance)
                if resolved:
                    endpoint = resolved
            if not endpoint:
                return None
            return ProxyProvider(
                endpoint=endpoint,
                model=pc.get("model", ""),
                instance=instance,
            )
        if name == "anthropic":
            return AnthropicProvider(
                model=pc.get("model", ""),
            )
        if name == "openai":
            return OpenAICompatibleProvider(
                endpoint=pc.get("endpoint", DEFAULT_ENDPOINT_OPENAI),
                model=pc.get("model", ""),
                context_length=pc.get("context_length", 0),
            )
        return None

    async def _auto_discover(self) -> AIProvider | None:
        """No auto-configure. Return None — user must configure explicitly."""
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

    async def respond(
        self, user_text: str, print_fn: Callable[[str], None] | None = None
    ) -> str | None:
        """Handle user input with agentic tool-calling loop.

        Streams text tokens to print_fn. When the model calls tools,
        executes them and feeds results back. Loops until no more tool
        calls or MAX_TOOL_ROUNDS reached.
        """
        if self._swapping:
            if print_fn:
                print_fn(AI_MSG.PROVIDER_CHANGING)
            return AI_MSG.PROVIDER_CHANGING

        provider = await self.ensure_provider()
        if not provider:
            msg = self._no_provider_message()
            self._say_ai(msg)
            if print_fn:
                print_fn(msg)
            return msg

        messages = self._build_messages(user_text)
        tools = build_ollama_tools()
        epoch = self._generation_epoch
        all_text: list[str] = []

        budget = self._get_budget()

        for round_num in range(MAX_TOOL_ROUNDS):
            # Compact if approaching budget (90%)
            if self._estimate_tokens(messages) > budget * 0.9:
                messages = self._compact_messages(messages, budget)

            # Epoch check — abort if provider swapped mid-loop
            if self._generation_epoch != epoch:
                if print_fn:
                    print_fn(AI_MSG.PROVIDER_CHANGING)
                return AI_MSG.PROVIDER_CHANGING

            # Stream from provider with tools
            result: GenerationResult | None = None
            in_think = False
            think_notified = False
            async for token in provider.generate_with_tools(messages, tools):
                if isinstance(token, GenerationResult):
                    result = token
                else:
                    # Detect <think> blocks — notify once, skip content
                    if "<think>" in token:
                        in_think = True
                        if not think_notified:
                            if print_fn:
                                print_fn("[thinking...]\n")
                            think_notified = True
                        continue
                    if "</think>" in token:
                        in_think = False
                        continue
                    if in_think:
                        continue
                    all_text.append(token)
                    if print_fn:
                        print_fn(token)

            if result is None:
                break

            # No tool calls — model is done
            if not result.tool_calls:
                break

            # Execute each tool call
            # Append assistant message with tool_calls to messages
            messages.append(
                {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": [
                        {"type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                        for tc in result.tool_calls
                    ],
                }
            )

            for tc in result.tool_calls:
                name = tc["name"]
                args = tc["arguments"]
                tool_result = await self._execute_tool(name, args)

                # Append tool result to messages
                messages.append(
                    {
                        "role": "tool",
                        "content": tool_result,
                    }
                )

                # Log to conversation
                args_short = json.dumps(args, default=str)[:100]
                result_short = tool_result[:200]
                self._say_ai(f"[tool: {name}({args_short})] → {result_short}")
                if print_fn:
                    print_fn(f"\n[tool: {name}] → {result_short}\n")

        response = "".join(all_text)
        if response:
            self._say_ai(response)
        return response

    async def _execute_tool(self, name: str, arguments: dict) -> str:
        """Execute a Fantastic tool by name. Returns result as string."""
        from ..dispatch import _TOOL_DISPATCH

        fn = _TOOL_DISPATCH.get(name)
        if not fn:
            return f"Error: unknown tool '{name}'"
        try:
            result = await fn(**arguments)
            if isinstance(result, (dict, list)):
                return json.dumps(result, default=str)
            return str(result)
        except Exception as e:
            return f"Error executing {name}: {e}"

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        """Estimate token count: ~4 chars per token."""
        total = 0
        for m in messages:
            total += len(m.get("content", ""))
            for tc in m.get("tool_calls", []):
                fn = tc.get("function", {})
                total += len(fn.get("name", ""))
                args = fn.get("arguments", "")
                total += len(str(args))
        return total // 4

    def _get_budget(self) -> int:
        """Get token budget for context (context_length - output reserve)."""
        ctx = 0
        if self._provider and hasattr(self._provider, "context_length"):
            ctx = self._provider.context_length
        if not ctx:
            ctx = 8192  # safe default
        return ctx - 2048  # reserve for output + tool calls

    def _build_messages(self, current_input: str) -> list[dict]:
        """Convert conversation buffer to chat messages with budget-aware truncation."""
        budget = self._get_budget()

        system_msg = {
            "role": "system",
            "content": (
                "You are a helpful AI assistant in the Fantastic Canvas environment. "
                "You have access to tools for creating agents, executing code, managing the canvas, "
                "and more. Use tools when the user's request requires taking actions. "
                "IMPORTANT: Never spawn cascades of fantastic_agent agents — you cannot communicate with them programmatically. "
                "If unsure whether to create agents or run code autonomously, ask the user first. "
                "When creating files, write them to the agent's own folder (.fantastic/agents/{agent_id}/) unless the user specifies a project path. "
                "This keeps the project directory clean."
            ),
        }
        user_msg = {"role": "user", "content": current_input}
        used = self._estimate_tokens([system_msg, user_msg])

        # Fill remaining budget with history (newest first)
        history_msgs: list[dict] = []
        for entry in reversed(conversation.read(max_lines=200)):
            who = entry["who"].lower()
            content = entry["message"]
            if who == "user":
                msg = {"role": "user", "content": content}
            elif who == "ai":
                msg = {"role": "assistant", "content": content}
            else:
                continue
            cost = len(content) // 4
            if used + cost > budget:
                break
            history_msgs.append(msg)
            used += cost

        return [system_msg] + list(reversed(history_msgs)) + [user_msg]

    @staticmethod
    def _compact_messages(messages: list[dict], budget: int) -> list[dict]:
        """Compact messages by truncating older tool results when over budget."""
        # Keep system (first) and last 4 messages intact
        if len(messages) <= 5:
            return messages
        head = messages[:1]  # system
        tail = messages[-4:]  # last 2 rounds
        middle = messages[1:-4]
        # Truncate tool results and long assistant text in middle
        compacted = []
        for m in middle:
            if m["role"] == "tool":
                content = m["content"]
                if len(content) > 200:
                    compacted.append({"role": "tool", "content": content[:200] + "...[truncated]"})
                else:
                    compacted.append(m)
            elif m["role"] == "assistant" and m.get("tool_calls"):
                # Keep tool_calls, truncate text
                compacted.append({
                    "role": "assistant",
                    "content": m["content"][:100] + "..." if len(m.get("content", "")) > 100 else m.get("content", ""),
                    "tool_calls": m["tool_calls"],
                })
            else:
                compacted.append(m)
        return head + compacted + tail

    # Default model examples per provider (for help message)
    _PROVIDER_EXAMPLES: dict[str, str] = {
        "ollama": "qwen3:8b-q4_K_M",
        "anthropic": "claude-sonnet-4-20250514",
        "integrated": "Qwen/Qwen3.5-4B",
        "openai": "my-model",
        "proxy": "<instance_url>",
    }

    def _no_provider_message(self) -> str:
        """Build a helpful message when no AI provider is configured."""
        providers = list(_PROVIDER_MAP.keys())
        lines = [
            "AI provider not configured.",
            "",
            "Usage: @ai start <provider> <model>",
            "",
        ]
        for p in providers:
            example = self._PROVIDER_EXAMPLES.get(p, "<model>")
            lines.append(f"  @ai start {p} {example}")
        lines.append("")
        lines.append("  @ai stop")
        return "\n".join(lines)

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
            "provider_name": config.get("provider_name") if config else None,
            "provider_config": config.get("provider_config") if config else None,
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
        pc = config.setdefault("provider_config", {})
        pc["model"] = model
        save_config(self._project_dir, config)
        self._say_ai(f"model set to {model}")

    async def pull_model(
        self, model: str, print_fn: Callable[[str], None] | None = None
    ) -> None:
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

    async def swap_provider(
        self,
        target: str,
        model: str | None = None,
        instance: str | None = None,
        force: bool = False,
    ) -> str:
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
                # Unload + stop current provider
                if self._provider is not None:
                    if hasattr(self._provider, "unload"):
                        self._provider.unload()
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
                        endpoint=result.endpoint,
                        model=chosen_model,
                        instance=instance,
                    )
                else:
                    self._provider = cls(endpoint=result.endpoint, model=chosen_model)

                pc: dict = {
                    "endpoint": result.endpoint,
                    "model": chosen_model,
                }
                if result.context_length:
                    pc["context_length"] = result.context_length
                if instance:
                    pc["instance"] = instance
                save_config(
                    self._project_dir,
                    {
                        "provider_name": target,
                        "provider_config": pc,
                    },
                )

                # Bump epoch if we didn't force (normal swap still invalidates old generations)
                if not force:
                    self._generation_epoch += 1

                if result.detail:
                    self._say_ai(result.detail)
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
