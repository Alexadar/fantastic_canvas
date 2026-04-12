"""Schedule tools — create, list, delete per-agent recurring schedules."""

from ..dispatch import ToolResult, register_dispatch, register_tool
from . import _state


@register_dispatch("create_schedule")
async def _create_schedule(
    agent_id: str = "",
    action: dict | None = None,
    interval_seconds: int = 60,
) -> ToolResult:
    if not agent_id:
        return ToolResult(data={"error": "agent_id is required"})
    if not action or "type" not in action:
        return ToolResult(
            data={"error": 'action is required with "type" field ("tool" or "prompt")'}
        )
    if action["type"] not in ("tool", "prompt"):
        return ToolResult(data={"error": f"Unknown action type: {action['type']}"})
    if action["type"] == "tool" and "tool" not in action:
        return ToolResult(data={"error": 'tool action requires "tool" field'})
    if action["type"] == "prompt" and "text" not in action:
        return ToolResult(data={"error": 'prompt action requires "text" field'})
    if not _state._scheduler:
        return ToolResult(data={"error": "Scheduler not initialized"})

    sch = _state._scheduler.add(agent_id, action, interval_seconds)
    return ToolResult(data={"schedule": sch, "agent_id": agent_id})


@register_tool("create_schedule")
async def create_schedule(
    agent_id: str,
    action: dict,
    interval_seconds: int = 60,
) -> dict:
    """Create a recurring schedule for an agent.

    Args:
        agent_id: The agent this schedule belongs to. Actions run as this agent.
        action: What to do each tick. Either {"type": "tool", "tool": "tool_name", "args": {...}}
                or {"type": "prompt", "text": "instruction for the AI"}.
        interval_seconds: How often to run (minimum 1 second). Default 60.
    """
    tr = await _create_schedule(
        agent_id=agent_id, action=action, interval_seconds=interval_seconds
    )
    return tr.data


@register_dispatch("list_schedules")
async def _list_schedules(agent_id: str = "") -> ToolResult:
    if not agent_id:
        return ToolResult(data={"error": "agent_id is required"})
    if not _state._scheduler:
        return ToolResult(data={"schedules": []})
    schedules = _state._scheduler.list_for_agent(agent_id)
    return ToolResult(data={"schedules": schedules, "agent_id": agent_id})


@register_tool("list_schedules")
async def list_schedules(agent_id: str) -> dict:
    """List active schedules for an agent.

    Args:
        agent_id: The agent whose schedules to list.
    """
    tr = await _list_schedules(agent_id=agent_id)
    return tr.data


@register_dispatch("delete_schedule")
async def _delete_schedule(agent_id: str = "", schedule_id: str = "") -> ToolResult:
    if not agent_id or not schedule_id:
        return ToolResult(data={"error": "agent_id and schedule_id are required"})
    if not _state._scheduler:
        return ToolResult(data={"error": "Scheduler not initialized"})
    removed = _state._scheduler.remove(agent_id, schedule_id)
    if not removed:
        return ToolResult(data={"error": f"Schedule {schedule_id} not found"})
    return ToolResult(data={"deleted": True, "schedule_id": schedule_id})


@register_tool("delete_schedule")
async def delete_schedule(agent_id: str, schedule_id: str) -> dict:
    """Delete a recurring schedule.

    Args:
        agent_id: The agent that owns the schedule.
        schedule_id: The schedule ID to delete.
    """
    tr = await _delete_schedule(agent_id=agent_id, schedule_id=schedule_id)
    return tr.data
