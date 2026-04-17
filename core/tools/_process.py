"""Process control tools + agent_call."""

import asyncio
import logging
import time

from ..dispatch import ToolResult, _DISPATCH, register_dispatch, register_tool
from . import _fire_broadcasts
from . import _state

logger = logging.getLogger(__name__)


@register_dispatch("agent_call")
async def _agent_call(
    target_agent_id: str = "",
    verb: str = "send",
    from_agent_id: str = "",
    message: str = "",
    **kwargs,
) -> ToolResult:
    """Universal inter-agent RPC.

    Routing:
      verb=="send" and target has PTY  → type `message` (or kwargs["text"]) into pty
      otherwise                        → look up _DISPATCH[f"{bundle}_{verb}"]
                                         and invoke with (agent_id=target, **kwargs)

    Any bundle that registers `{bundle}_{verb}` becomes reachable. Core knows
    no bundle names.
    """
    target = target_agent_id
    agent = _state._engine.get_agent(target)
    if agent is None:
        return ToolResult(data={"error": f"Agent {target} not found"})

    # Legacy: agent_call(target, message="hi") is sugar for verb="send" text="hi".
    if verb == "send" and "text" not in kwargs and message:
        kwargs["text"] = message

    timestamp = time.time()
    has_process = _state._process_runner and _state._process_runner.exists(target)

    # 1) verb=send + PTY  →  type into the pty.
    if verb == "send" and has_process:
        text = kwargs.get("text", "")
        for ch in text:
            await _state._process_runner.write(target, ch)
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.5)
        await _state._process_runner.write(target, "\r")
        logger.info(f"agent_call: typed {len(text)} chars + Enter to pty")
        return ToolResult(
            data={
                "delivered": True,
                "delivered_to_process": True,
                "delivered_to_chat": False,
                "target_agent_id": target,
                "verb": verb,
                "timestamp": timestamp,
            },
        )

    # 2) Dispatch to `{bundle}_{verb}`.
    bundle = agent.get("bundle", "")
    handler = _DISPATCH.get(f"{bundle}_{verb}") if bundle else None
    if handler is None:
        return ToolResult(
            data={
                "delivered": False,
                "error": f"no '{bundle}_{verb}' handler on agent {target}",
                "target_agent_id": target,
                "verb": verb,
            },
        )

    from ..trace import trace

    call_args = {"agent_id": target, **kwargs}
    result = await trace(
        "agent_call",
        from_agent_id or target,
        f"{bundle}_{verb}",
        call_args,
        handler,
    )
    if isinstance(result, ToolResult) and result.broadcast:
        from ..bus import bus as _bus

        for msg in result.broadcast:
            await _bus.broadcast(msg)

    data = result.data if isinstance(result, ToolResult) else {"raw": str(result)}
    if not isinstance(data, dict):
        data = {"result": data}
    return ToolResult(
        data={
            "delivered": True,
            "delivered_to_process": False,
            "delivered_to_chat": True,
            "target_agent_id": target,
            "verb": verb,
            "timestamp": timestamp,
            **data,
        },
    )


@register_tool("agent_call")
async def agent_call(
    target_agent_id: str,
    verb: str = "send",
    from_agent_id: str = "",
    message: str = "",
    **kwargs,
) -> dict:
    """Universal inter-agent RPC.

    `verb="send"` + PTY agent → writes message into the pty.
    Otherwise looks up `{bundle}_{verb}` in the dispatch registry and calls it.

    Args:
        target_agent_id: The agent to invoke.
        verb: The verb to call (default "send").
        from_agent_id: Optional — the calling agent's id (trace tag).
        message: Text to send when verb=="send" (legacy shorthand for text).
        **kwargs: Verb-specific arguments.
    """
    tr = await _agent_call(
        target_agent_id=target_agent_id,
        verb=verb,
        from_agent_id=from_agent_id,
        message=message,
        **kwargs,
    )
    await _fire_broadcasts(tr)
    return tr.data


@register_dispatch("process_output")
async def _process_output(agent_id: str = "", max_lines: int = 200) -> ToolResult:
    raw = _state._process_runner.get_scrollback(agent_id)
    if not raw:
        raw = _state._process_runner.load_scrollback_from_disk(agent_id)
    if not raw:
        return ToolResult(
            data={"error": f"Process {agent_id} not found or has no output"}
        )
    lines = raw.split("\n")
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return ToolResult(data={"output": "\n".join(lines), "lines": len(lines)})


@register_dispatch("process_restart")
async def _process_restart(agent_id: str = "") -> ToolResult:
    if not agent_id:
        return ToolResult(data={"error": "agent_id is required"})
    try:
        await _state._process_runner.restart(agent_id)
    except ValueError as e:
        return ToolResult(data={"error": str(e)})
    return ToolResult(
        data={"agent_id": agent_id, "restarted": True},
        broadcast=[
            {"type": "process_closed", "agent_id": agent_id},
            {"type": "process_started", "agent_id": agent_id},
        ],
    )


@register_dispatch("process_signal")
async def _process_signal(agent_id: str = "", signal: int = 2) -> ToolResult:
    try:
        _state._process_runner.send_signal(agent_id, signal)
    except ValueError as e:
        return ToolResult(data={"error": str(e)})
    return ToolResult(data={"agent_id": agent_id, "signal": signal})
