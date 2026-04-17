"""scheduler bundle — recurring-task scheduler as an agent.

One agent per scheduler instance (usually just `scheduler_main`). Each
scheduler owns a set of schedules persisted in
`.fantastic/agents/{sched_id}/schedules.json`. Every fire is:

- **broadcast** on the bus: `schedule_fired` event on the scheduler
  agent's inbox AND on the target agent's inbox (observers can watch
  whichever makes sense);
- **persisted** to `.fantastic/agents/{sched_id}/history.jsonl`
  (ring-trimmed to last 500 entries).

Verbs (via `agent_call`, handler names `scheduler_{verb}`):

  schedule     add a schedule; returns {schedule_id}
  unschedule   remove; returns {removed: bool}
  list         current schedules
  pause        pause one (by schedule_id) or all (if omitted)
  resume       opposite
  tick_now     fire a schedule immediately (testing / manual trigger)
  history      last N `schedule_fired` events (optionally filtered)
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from pathlib import Path

from core.dispatch import ToolResult, _DISPATCH, register_dispatch

logger = logging.getLogger(__name__)

NAME = "scheduler"
HISTORY_MAX = 500

_engine = None
_tick_tasks: dict[str, asyncio.Task] = {}  # sched_id → tick loop task
_schedules_cache: dict[str, list[dict]] = {}  # sched_id → list[schedule dict]


# ─── sidecar paths ───────────────────────────────────────────────


def _sched_path(sched_id: str) -> Path:
    return (
        Path(_engine.project_dir)
        / ".fantastic"
        / "agents"
        / sched_id
        / "schedules.json"
    )


def _history_path(sched_id: str) -> Path:
    return (
        Path(_engine.project_dir) / ".fantastic" / "agents" / sched_id / "history.jsonl"
    )


def _load_schedules(sched_id: str) -> list[dict]:
    cached = _schedules_cache.get(sched_id)
    if cached is not None:
        return cached
    path = _sched_path(sched_id)
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached = []
    else:
        cached = []
    _schedules_cache[sched_id] = cached
    return cached


def _save_schedules(sched_id: str) -> None:
    path = _sched_path(sched_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_schedules_cache.get(sched_id, []), indent=2), encoding="utf-8"
    )


def _append_history(sched_id: str, event: dict) -> None:
    path = _history_path(sched_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Append, then ring-trim if oversized.
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")
    # Cheap check: if file grew past 2*HISTORY_MAX lines, rewrite last HISTORY_MAX.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 2 * HISTORY_MAX:
            path.write_text("\n".join(lines[-HISTORY_MAX:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def _read_history(sched_id: str, limit: int = 100) -> list[dict]:
    path = _history_path(sched_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ─── bundle setup ───────────────────────────────────────────────


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    global _engine
    _engine = engine
    from core.tools._state import _on_subagents_loaded

    _on_subagents_loaded.append(_start_all_tick_loops)
    # When a scheduler agent is deleted, kill its tick loop + drop cache.
    engine.store.on_agent_deleted(_on_agent_deleted)
    return {}


def _on_agent_deleted(agent_id: str) -> None:
    task = _tick_tasks.pop(agent_id, None)
    if task and not task.done():
        task.cancel()
    _schedules_cache.pop(agent_id, None)


def _start_all_tick_loops(engine) -> None:
    """Hook: called after all bundles load. Spawn tick loop per scheduler agent."""
    for a in engine.store.list_agents():
        if a.get("bundle") != "scheduler":
            continue
        sid = a["id"]
        if sid in _tick_tasks and not _tick_tasks[sid].done():
            continue
        _tick_tasks[sid] = asyncio.create_task(_tick_loop(sid))


async def on_add(project_dir, name: str = "") -> None:
    """Create ONE scheduler agent on explicit `add scheduler`."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    display = name or "main"
    for a in store.list_agents():
        if a.get("bundle") == "scheduler" and a.get("display_name") == display:
            print(f"  scheduler '{display}' already exists: {a['id']}")
            return
    agent = store.create_agent(bundle="scheduler")
    store.update_agent_meta(
        agent["id"], display_name=display, tick_sec=1.0, paused=False
    )
    # Tick loop will start on next `_start_all_tick_loops` call; if the bundle is
    # added at runtime (post-boot), spawn one now.
    if _engine is not None and agent["id"] not in _tick_tasks:
        _tick_tasks[agent["id"]] = asyncio.create_task(_tick_loop(agent["id"]))
    print(f"  scheduler '{display}' created: {agent['id']}")


# ─── tick loop ──────────────────────────────────────────────────


async def _tick_loop(sched_id: str) -> None:
    """Per-scheduler-agent tick loop. Fires due schedules, emits events."""
    try:
        while True:
            agent = _engine.get_agent(sched_id) if _engine else None
            if agent is None:
                return  # scheduler agent deleted
            tick_sec = float(agent.get("tick_sec") or 1.0)
            await asyncio.sleep(tick_sec)
            if agent.get("paused"):
                continue
            now = time.time()
            schedules = _load_schedules(sched_id)
            for sch in list(schedules):
                if sch.get("paused") or sch.get("enabled") is False:
                    continue
                if now < sch.get("next_run", 0):
                    continue
                await _fire(sched_id, sch)
                sch["run_count"] = sch.get("run_count", 0) + 1
                sch["next_run"] = time.time() + sch["interval_seconds"]
                _save_schedules(sched_id)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("scheduler tick loop crashed for %s", sched_id)


async def _fire(sched_id: str, sch: dict) -> None:
    """Invoke a schedule's action; emit + persist a `schedule_fired` event."""
    from core.bus import bus
    from core.trace import trace

    for_id = sch.get("for_agent_id") or sch.get("target_agent_id", "")
    action = sch.get("action", {})
    action_type = action.get("type", "")
    ts = time.time()
    result_data = None
    error = None
    try:
        if action_type == "tool":
            fn = _DISPATCH.get(action.get("tool", ""))
            if fn is None:
                error = f"tool {action.get('tool')!r} not in dispatch"
            else:
                args = dict(action.get("args", {}))
                args["agent_id"] = for_id
                r = await trace("scheduler", sched_id, action["tool"], args, fn)
                if isinstance(r, ToolResult):
                    result_data = r.data
                    for msg in r.broadcast:
                        await bus.broadcast(msg)
                else:
                    result_data = r
        elif action_type == "prompt":
            agent = _engine.get_agent(for_id) if for_id else None
            bundle = agent.get("bundle", "") if agent else ""
            handler = _DISPATCH.get(f"{bundle}_send") if bundle else None
            if handler is None:
                error = f"no {bundle}_send handler for {for_id}"
            else:
                args = {"agent_id": for_id, "text": action.get("text", "")}
                r = await trace("scheduler", sched_id, f"{bundle}_send", args, handler)
                if isinstance(r, ToolResult):
                    result_data = r.data
                    for msg in r.broadcast:
                        await bus.broadcast(msg)
                else:
                    result_data = r
        else:
            error = f"unknown action type {action_type!r}"
    except Exception as e:
        error = f"{type(e).__name__}: {e}"

    event = {
        "type": "schedule_fired",
        "schedule_id": sch["id"],
        "scheduler_id": sched_id,
        "for_agent_id": for_id,
        "action": action,
        "result": result_data,
        "error": error,
        "ts": ts,
        "duration_ms": int((time.time() - ts) * 1000),
    }
    _append_history(sched_id, event)
    # Emit on the scheduler agent's inbox (audit) and the target's inbox (reaction).
    await bus.emit(sched_id, "schedule_fired", event)
    if for_id and for_id != sched_id:
        await bus.emit(for_id, "schedule_fired", event)


# ─── verb handlers ──────────────────────────────────────────────


def _require_scheduler(agent_id: str) -> tuple[dict | None, ToolResult | None]:
    if not agent_id:
        return None, ToolResult(data={"error": "agent_id required"})
    a = _engine.get_agent(agent_id)
    if not a or a.get("bundle") != "scheduler":
        return None, ToolResult(data={"error": f"{agent_id} is not a scheduler agent"})
    return a, None


@register_dispatch("scheduler_schedule")
async def _schedule(
    agent_id: str = "",
    for_agent_id: str = "",
    action: dict | None = None,
    interval_seconds: int = 60,
    **_kw,
) -> ToolResult:
    _, err = _require_scheduler(agent_id)
    if err:
        return err
    if not for_agent_id:
        return ToolResult(data={"error": "for_agent_id required"})
    if not action or "type" not in action:
        return ToolResult(data={"error": "action requires a 'type' field"})
    t = action["type"]
    if t not in ("tool", "prompt"):
        return ToolResult(data={"error": f"unknown action type {t!r}"})
    if t == "tool" and "tool" not in action:
        return ToolResult(data={"error": "tool action requires 'tool' field"})
    if t == "prompt" and "text" not in action:
        return ToolResult(data={"error": "prompt action requires 'text' field"})

    schedules = _load_schedules(agent_id)
    sch = {
        "id": f"sch_{secrets.token_hex(4)}",
        "for_agent_id": for_agent_id,
        "action": action,
        "interval_seconds": max(1, int(interval_seconds)),
        "created_at": time.time(),
        "next_run": time.time() + max(1, int(interval_seconds)),
        "run_count": 0,
        "paused": False,
    }
    schedules.append(sch)
    _save_schedules(agent_id)
    return ToolResult(data={"schedule_id": sch["id"], "schedule": sch})


@register_dispatch("scheduler_unschedule")
async def _unschedule(agent_id: str = "", schedule_id: str = "", **_kw) -> ToolResult:
    _, err = _require_scheduler(agent_id)
    if err:
        return err
    if not schedule_id:
        return ToolResult(data={"error": "schedule_id required"})
    schedules = _load_schedules(agent_id)
    before = len(schedules)
    _schedules_cache[agent_id] = [s for s in schedules if s["id"] != schedule_id]
    removed = len(_schedules_cache[agent_id]) < before
    if removed:
        _save_schedules(agent_id)
    return ToolResult(data={"removed": removed, "schedule_id": schedule_id})


@register_dispatch("scheduler_list")
async def _list(agent_id: str = "", **_kw) -> ToolResult:
    _, err = _require_scheduler(agent_id)
    if err:
        return err
    return ToolResult(data={"schedules": list(_load_schedules(agent_id))})


@register_dispatch("scheduler_pause")
async def _pause(agent_id: str = "", schedule_id: str = "", **_kw) -> ToolResult:
    a, err = _require_scheduler(agent_id)
    if err:
        return err
    if schedule_id:
        touched = 0
        for s in _load_schedules(agent_id):
            if s["id"] == schedule_id:
                s["paused"] = True
                touched += 1
        if touched:
            _save_schedules(agent_id)
        return ToolResult(data={"paused": touched > 0, "schedule_id": schedule_id})
    # No id → pause entire scheduler.
    _engine.update_agent_meta(agent_id, paused=True)
    return ToolResult(data={"paused": True, "scheduler_id": agent_id})


@register_dispatch("scheduler_resume")
async def _resume(agent_id: str = "", schedule_id: str = "", **_kw) -> ToolResult:
    a, err = _require_scheduler(agent_id)
    if err:
        return err
    if schedule_id:
        touched = 0
        for s in _load_schedules(agent_id):
            if s["id"] == schedule_id:
                s["paused"] = False
                touched += 1
        if touched:
            _save_schedules(agent_id)
        return ToolResult(data={"resumed": touched > 0, "schedule_id": schedule_id})
    _engine.update_agent_meta(agent_id, paused=False)
    return ToolResult(data={"resumed": True, "scheduler_id": agent_id})


@register_dispatch("scheduler_tick_now")
async def _tick_now(agent_id: str = "", schedule_id: str = "", **_kw) -> ToolResult:
    _, err = _require_scheduler(agent_id)
    if err:
        return err
    if not schedule_id:
        return ToolResult(data={"error": "schedule_id required"})
    for s in _load_schedules(agent_id):
        if s["id"] == schedule_id:
            await _fire(agent_id, s)
            s["run_count"] = s.get("run_count", 0) + 1
            _save_schedules(agent_id)
            return ToolResult(data={"fired": True, "schedule_id": schedule_id})
    return ToolResult(data={"error": f"schedule {schedule_id} not found"})


@register_dispatch("scheduler_history")
async def _history(
    agent_id: str = "", schedule_id: str = "", limit: int = 100, **_kw
) -> ToolResult:
    _, err = _require_scheduler(agent_id)
    if err:
        return err
    entries = _read_history(agent_id, limit=max(1, min(500, int(limit))))
    if schedule_id:
        entries = [e for e in entries if e.get("schedule_id") == schedule_id]
    return ToolResult(data={"history": entries, "count": len(entries)})
