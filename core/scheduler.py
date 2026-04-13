"""Persistent per-agent scheduler — recurring tool calls and AI prompts.

Schedules are stored per-agent in .fantastic/agents/{id}/schedules.json.
The tick loop checks every second for due schedules and executes them.
Agent deletion auto-removes schedules (directory is rmtree'd).
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class Scheduler:
    """Per-agent persistent scheduler with async tick loop."""

    def __init__(self, agents_dir: Path):
        self._agents_dir = agents_dir
        self._cache: dict[str, list[dict]] = {}  # agent_id → schedules
        self._task: asyncio.Task | None = None

    # ─── Persistence ──────────────────────────────────────────

    def load_all(self) -> None:
        """Scan all agent dirs for schedules.json, populate cache."""
        if not self._agents_dir.exists():
            return
        for entry in self._agents_dir.iterdir():
            if entry.is_dir():
                schedules = self._load_agent(entry.name)
                if schedules:
                    self._cache[entry.name] = schedules

    def _load_agent(self, agent_id: str) -> list[dict]:
        path = self._agents_dir / agent_id / "schedules.json"
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def _save_agent(self, agent_id: str) -> None:
        schedules = self._cache.get(agent_id, [])
        path = self._agents_dir / agent_id / "schedules.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(schedules, indent=2), encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to save schedules for %s: %s", agent_id, e)

    # ─── CRUD ─────────────────────────────────────────────────

    def add(self, agent_id: str, action: dict, interval_seconds: int) -> dict:
        """Add a schedule to an agent. Returns the new schedule dict."""
        sch: dict[str, Any] = {
            "id": f"sch_{secrets.token_hex(4)}",
            "action": action,
            "interval_seconds": max(1, interval_seconds),
            "created_at": time.time(),
            "next_run": time.time() + interval_seconds,
            "run_count": 0,
            "enabled": True,
        }
        self._cache.setdefault(agent_id, []).append(sch)
        self._save_agent(agent_id)
        return sch

    def remove(self, agent_id: str, schedule_id: str) -> bool:
        """Remove a schedule by ID from an agent."""
        schedules = self._cache.get(agent_id, [])
        before = len(schedules)
        self._cache[agent_id] = [s for s in schedules if s["id"] != schedule_id]
        if len(self._cache[agent_id]) < before:
            self._save_agent(agent_id)
            return True
        return False

    def list_for_agent(self, agent_id: str) -> list[dict]:
        """List schedules for a specific agent."""
        return list(self._cache.get(agent_id, []))

    # ─── Tick loop ────────────────────────────────────────────

    async def start(self, dispatch: dict, broadcast_fn: Any) -> None:
        """Start the background tick loop."""
        self._task = asyncio.create_task(self._tick_loop(dispatch, broadcast_fn))

    async def stop(self) -> None:
        """Cancel the tick loop gracefully."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _tick_loop(self, dispatch: dict, broadcast_fn: Any) -> None:
        """Every 1s: check all agents' schedules for due items."""
        try:
            while True:
                await asyncio.sleep(1)
                now = time.time()
                for agent_id in list(self._cache.keys()):
                    for sch in self._cache.get(agent_id, []):
                        if not sch["enabled"] or now < sch["next_run"]:
                            continue
                        await self._execute(agent_id, sch, dispatch, broadcast_fn)
                        sch["run_count"] += 1
                        sch["next_run"] = now + sch["interval_seconds"]
                        self._save_agent(agent_id)
        except asyncio.CancelledError:
            pass

    async def _execute(
        self, agent_id: str, sch: dict, dispatch: dict, broadcast_fn: Any
    ) -> None:
        """Execute a schedule's action, scoped to owning agent.

        Any ToolResult.broadcast returned by the action is fired via broadcast_fn
        so events reach the bus (previously dropped).
        """
        action = sch["action"]
        action_type = action.get("type", "")
        try:
            from core.trace import trace

            result = None
            if action_type == "tool":
                fn = dispatch.get(action["tool"])
                if fn:
                    args = dict(action.get("args", {}))
                    args["agent_id"] = agent_id  # always scoped
                    result = await trace(
                        "scheduler", agent_id, action["tool"], args, fn, **args
                    )
            elif action_type == "prompt":
                # Route to the agent's bundle `_send` dispatch.
                agent_dir = self._agents_dir / agent_id
                bundle = _read_agent_bundle(agent_dir)
                if bundle:
                    handler = dispatch.get(f"{bundle}_send")
                    if handler:
                        send_args = {"agent_id": agent_id, "text": action["text"]}
                        result = await trace(
                            "scheduler",
                            agent_id,
                            f"{bundle}_send",
                            send_args,
                            handler,
                            **send_args,
                        )
                    else:
                        logger.warning(
                            "Schedule %s: no %s_send handler (agent %s offline?)",
                            sch["id"],
                            bundle,
                            agent_id,
                        )

            # Route any returned broadcasts through the bus.
            broadcasts = getattr(result, "broadcast", None)
            if broadcasts and broadcast_fn is not None:
                for msg in broadcasts:
                    await broadcast_fn(msg)
            logger.debug(
                "Schedule %s executed for agent %s (run #%d)",
                sch["id"],
                agent_id,
                sch["run_count"] + 1,
            )
        except Exception as e:
            logger.warning(
                "Schedule %s failed for agent %s: %s", sch["id"], agent_id, e
            )


def _read_agent_bundle(agent_dir: Path) -> str:
    """Read bundle name from agent.json."""
    try:
        data = json.loads((agent_dir / "agent.json").read_text(encoding="utf-8"))
        return data.get("bundle", "")
    except (OSError, json.JSONDecodeError):
        return ""
