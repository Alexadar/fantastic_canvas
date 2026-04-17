"""Dispatch tracing — wrap any dispatch invocation to emit `on_message` events.

Usage:
    from core.trace import trace

    # Instead of: result = await fn(**args)
    result = await trace("ws", agent_id, tool_name, args, fn)

`args` is passed both as the audit record AND as the kwargs for `fn`.
Keeping a single dict (rather than splatting) avoids kwarg collisions
when a dispatched tool itself takes an arg named `tool` / `source` / etc.
"""

from __future__ import annotations

import time
from typing import Callable

from .bus import bus


async def trace(
    source: str,
    source_agent_id: str | None,
    tool_name: str,
    args: dict,
    fn: Callable,
) -> object:
    """Invoke `fn(**args)`, publish a core_message event, return the result."""
    ts = time.time()
    src_tag = f"{source}:{source_agent_id or '-'}"
    try:
        result = await fn(**args)
    except Exception as e:
        duration_ms = int((time.time() - ts) * 1000)
        await bus.emit_core_message(
            {
                "ts": ts,
                "source": source,
                "source_agent_id": source_agent_id,
                "tool": tool_name,
                "args": args,
                "status": "error",
                "duration_ms": duration_ms,
                "result": None,
                "error": str(e),
                "message": f"[{src_tag}] {tool_name}(...) → error: {e}",
            }
        )
        raise

    duration_ms = int((time.time() - ts) * 1000)
    await bus.emit_core_message(
        {
            "ts": ts,
            "source": source,
            "source_agent_id": source_agent_id,
            "tool": tool_name,
            "args": args,
            "status": "ok",
            "duration_ms": duration_ms,
            "result": result,
            "error": None,
            "message": f"[{src_tag}] {tool_name}(...) → ok ({duration_ms}ms)",
        }
    )
    return result
