"""Per-agent message bus. Core orchestrator has no HTTP — transport bundles
drain the bus into their chosen transport (WS, gRPC, stdio, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable

logger = logging.getLogger(__name__)


class Bus:
    """Message bus with per-agent inboxes, global firehose, and mirroring.

    - emit(agent_id, event, data): route a message to one agent's inbox.
      If `source` has watchers, also deliver to each watcher's inbox.
    - recv(agent_id): async iterator of messages for this agent.
    - broadcast(msg): global firehose (for messages without a specific agent target).
    - subscribe_global(fn): listen to the global firehose.
    - watch(source, target): mirror `source`'s emissions into `target`'s inbox.
    - unwatch(source, target): stop mirroring.
    """

    def __init__(self):
        self._inboxes: dict[str, asyncio.Queue[dict]] = {}
        self._global_subscribers: list[Callable] = []
        # {source_agent_id: set of target_agent_ids watching it}
        self._watchers: dict[str, set[str]] = {}
        # on_message subscribers — pure pub/sub, no accumulation
        self._on_message: list[Callable] = []

    # ─── Per-agent inbox ──────────────────────────────────────

    def _inbox(self, agent_id: str) -> asyncio.Queue[dict]:
        q = self._inboxes.get(agent_id)
        if q is None:
            q = asyncio.Queue()
            self._inboxes[agent_id] = q
        return q

    async def emit(self, agent_id: str, event: str, data: dict | None = None) -> None:
        """Enqueue an event message to agent's inbox, plus to anyone watching them."""
        msg = {"type": "event", "event": event, "data": data or {}}
        await self._inbox(agent_id).put(msg)
        # Mirror to watchers
        for target in self._watchers.get(agent_id, ()):
            await self._inbox(target).put(msg)

    async def recv(self, agent_id: str) -> AsyncIterator[dict]:
        """Async iterator over inbox messages. Blocks until messages arrive."""
        q = self._inbox(agent_id)
        while True:
            msg = await q.get()
            yield msg

    async def get(self, agent_id: str, timeout: float | None = None) -> dict | None:
        """Pull one message, optionally with timeout."""
        q = self._inbox(agent_id)
        try:
            if timeout is not None:
                return await asyncio.wait_for(q.get(), timeout=timeout)
            return await q.get()
        except asyncio.TimeoutError:
            return None

    def clear_inbox(self, agent_id: str) -> None:
        """Drop inbox (on agent delete)."""
        self._inboxes.pop(agent_id, None)
        # Remove as a watch source
        self._watchers.pop(agent_id, None)
        # Remove as a watcher of anything
        for targets in self._watchers.values():
            targets.discard(agent_id)

    # ─── Global firehose ──────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        """Fire to all global subscribers (for canvases watching creations, etc.).

        ALSO: if msg has `agent_id`, route to that agent's inbox as an event.
        """
        for fn in list(self._global_subscribers):
            try:
                await fn(msg)
            except Exception:
                logger.exception("Global subscriber failed")

        aid = msg.get("agent_id")
        if aid:
            event_name = msg.get("type", "event")
            data = {k: v for k, v in msg.items() if k not in ("type", "agent_id")}
            await self.emit(aid, event_name, data)

    def subscribe_global(self, fn: Callable) -> Callable:
        """Register a global firehose subscriber. Returns unsubscribe callable."""
        self._global_subscribers.append(fn)

        def unsubscribe():
            try:
                self._global_subscribers.remove(fn)
            except ValueError:
                pass

        return unsubscribe

    # ─── Watch (event mirroring) ──────────────────────────────

    def watch(self, source_agent: str, target_agent: str) -> None:
        """Mirror source's emissions into target's inbox."""
        self._watchers.setdefault(source_agent, set()).add(target_agent)

    def unwatch(self, source_agent: str, target_agent: str) -> None:
        """Stop mirroring."""
        targets = self._watchers.get(source_agent)
        if targets:
            targets.discard(target_agent)
            if not targets:
                self._watchers.pop(source_agent, None)

    # ─── on_message channel (dispatch trace) ──────────────────

    def on_message(self, fn: Callable) -> Callable:
        """Subscribe to every dispatch trace event. Returns unsubscribe callable.

        Pure pub/sub: no buffer, no backpressure. If nobody is subscribed
        when an event fires, it's gone. Subscriber fn receives a dict; may
        be sync or async.
        """
        self._on_message.append(fn)

        def unsubscribe():
            try:
                self._on_message.remove(fn)
            except ValueError:
                pass

        return unsubscribe

    async def emit_core_message(self, event: dict) -> None:
        """Fire event to every on_message subscriber. No-op if none."""
        if not self._on_message:
            return
        for fn in list(self._on_message):
            try:
                result = fn(event)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                logger.exception("on_message subscriber failed")


# Global singleton — wired into engine/dispatch
bus = Bus()
