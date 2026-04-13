"""Dispatch tracing — wrap any dispatch invocation to emit `on_message` events.

Usage:
    from core.trace import trace

    # Instead of: result = await fn(**args)
    result = await trace("ws", agent_id, tool_name, args, fn, **args)

Wire this around every place that invokes `_DISPATCH[name]`. The event
is published to `bus.on_message` subscribers (pure pub/sub, no buffer).
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .bus import bus


async def trace(
    source: str,
    source_agent_id: str | None,
    tool: str,
    args: dict,
    fn: Callable,
    *call_args: Any,
    **call_kwargs: Any,
) -> Any:
    """Invoke `fn(*call_args, **call_kwargs)` and publish a core_message event.

    Returns whatever fn returns. Re-raises whatever fn raises.
    """
    ts = time.time()
    src_tag = f"{source}:{source_agent_id or '-'}"
    try:
        result = await fn(*call_args, **call_kwargs)
    except Exception as e:
        duration_ms = int((time.time() - ts) * 1000)
        await bus.emit_core_message(
            {
                "ts": ts,
                "source": source,
                "source_agent_id": source_agent_id,
                "tool": tool,
                "args": args,
                "status": "error",
                "duration_ms": duration_ms,
                "result": None,
                "error": str(e),
                "message": f"[{src_tag}] {tool}(...) → error: {e}",
            }
        )
        raise

    duration_ms = int((time.time() - ts) * 1000)
    await bus.emit_core_message(
        {
            "ts": ts,
            "source": source,
            "source_agent_id": source_agent_id,
            "tool": tool,
            "args": args,
            "status": "ok",
            "duration_ms": duration_ms,
            "result": result,
            "error": None,
            "message": f"[{src_tag}] {tool}(...) → ok ({duration_ms}ms)",
        }
    )
    return result
