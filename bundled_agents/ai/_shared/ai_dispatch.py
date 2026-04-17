"""Factory for AI bundle dispatch handlers.

Each bundle calls `register_ai_dispatch(bundle_name, provider_factory)` to get
a dict of handlers ready to return from `register_dispatch()`.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from core.dispatch import ToolResult

from .agentic_loop import run_agentic_loop
from .chat_storage import load_history, save_message
from .messages import build_messages
from .provider_pool import ProviderPool
from .tool_schema import build_tool_schema

logger = logging.getLogger(__name__)


class AiBundleRuntime:
    """Runtime state for one AI bundle (ollama, openai, etc.).

    Holds provider pool, abort flags, and reference to engine/broadcast.
    Each bundle's tools.py creates one instance.
    """

    def __init__(
        self,
        bundle: str,
        provider_factory: Callable[[dict], Any],
    ):
        self.bundle = bundle
        self.pool = ProviderPool(provider_factory)
        self.abort: dict[str, bool] = {}
        self.engine = None
        self.broadcast: Callable | None = None

    def register(self, engine, broadcast):
        """Wire to engine + broadcast. Register agent delete hook for cleanup."""
        self.engine = engine
        self.broadcast = broadcast
        engine.store.on_agent_deleted(lambda aid: self.pool.release(aid))

    def make_dispatch_handlers(self) -> dict[str, Callable]:
        """Return dispatch handler dict. Keys are prefixed with bundle name."""
        b = self.bundle
        return {
            f"{b}_send": self._send,
            f"{b}_interrupt": self._interrupt,
            f"{b}_save_message": self._save_msg,
            f"{b}_history": self._history,
            f"{b}_configure": self._configure,
        }

    async def _send(self, agent_id: str = "", text: str = "", **_kw) -> ToolResult:
        if not agent_id or not text:
            return ToolResult(data={"error": "agent_id and text required"})
        agent = self.engine.get_agent(agent_id)
        if not agent:
            return ToolResult(data={"error": f"Agent {agent_id} not found"})

        try:
            provider = self.pool.get_or_create(agent_id, agent)
        except Exception as e:
            await self.broadcast(
                {
                    "type": f"{self.bundle}_error",
                    "agent_id": agent_id,
                    "error": f"Provider init failed: {e}",
                }
            )
            return ToolResult(data={"error": str(e)})

        history = load_history(self.engine.project_dir, agent_id)
        ctx_len = getattr(provider, "context_length", 0) or 8192
        messages = build_messages(history, text, context_length=ctx_len)
        tools = build_tool_schema()

        self.abort[agent_id] = False
        response = await run_agentic_loop(
            agent_id=agent_id,
            bundle=self.bundle,
            provider=provider,
            messages=messages,
            tools=tools,
            broadcast=self.broadcast,
            abort_flag=self.abort,
        )

        # Broadcast context usage
        ctx_used = sum(len(m.get("content") or "") for m in messages) // 4
        ctx_max = getattr(provider, "context_length", 0) or 0
        provider_online = provider is not None
        await self.broadcast(
            {
                "type": "context_usage",
                "agent_id": agent_id,
                "used": ctx_used,
                "max": ctx_max,
                "provider": str(provider) if provider else None,
                "provider_online": provider_online,
            }
        )

        return ToolResult(data={"ok": True, "response": response})

    async def _interrupt(self, agent_id: str = "", **_kw) -> ToolResult:
        self.abort[agent_id] = True
        return ToolResult(data={"ok": True, "agent_id": agent_id})

    async def _save_msg(
        self,
        agent_id: str = "",
        role: str = "user",
        text: str = "",
        mode: str = "chat",
        **_kw,
    ) -> ToolResult:
        if not agent_id or not text:
            return ToolResult(data={"error": "agent_id and text required"})
        msg = save_message(self.engine.project_dir, agent_id, role, text, mode)
        return ToolResult(data={"ok": True, "message": msg})

    async def _history(self, agent_id: str = "", **_kw) -> ToolResult:
        msgs = load_history(self.engine.project_dir, agent_id)
        return ToolResult(
            data={"ok": True},
            reply=[
                {
                    "type": f"{self.bundle}_history_response",
                    "agent_id": agent_id,
                    "messages": msgs,
                }
            ],
        )

    async def _configure(self, agent_id: str = "", **options) -> ToolResult:
        if not agent_id:
            return ToolResult(data={"error": "agent_id required"})
        try:
            self.engine.update_agent_meta(agent_id, **options)
        except Exception as e:
            return ToolResult(data={"error": str(e)})
        # Force re-init with new config
        self.pool.release(agent_id)
        return ToolResult(
            data={"ok": True, "agent_id": agent_id, **options},
            broadcast=[{"type": "agent_updated", "agent_id": agent_id, **options}],
        )
