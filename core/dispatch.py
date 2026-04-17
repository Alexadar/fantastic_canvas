"""
Dispatch layer — ToolResult dataclass and dispatch function.

ToolResult is the universal return type for all business logic operations.
Each operation returns data, plus optional broadcast/reply message lists
that transports (WS, REST) handle appropriately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Populated by tools at import time
_DISPATCH: dict[str, Any] = {}
_TOOL_DISPATCH: dict[str, Any] = {}

# Private per-bundle verb table. Shape: _BUNDLE_VERBS[bundle][verb] → callable.
# Callers never reach these names directly — only through `agent_call(target,
# verb, **args)` which resolves `{bundle}` from the target agent and looks
# the verb up here.
_BUNDLE_VERBS: dict[str, dict[str, Any]] = {}


@dataclass
class ToolResult:
    """Result from a dispatched tool operation.

    Attributes:
        data:      Business result (dict/list/str/None).
        broadcast: Messages to send to ALL connected WS clients.
        reply:     Messages to send only to the requesting WS client.
    """

    data: Any = None
    broadcast: list[dict] = field(default_factory=list)
    reply: list[dict] = field(default_factory=list)


def register_dispatch(name: str = ""):
    """Decorator: register inner function to _DISPATCH."""

    def decorator(fn):
        _DISPATCH[name or fn.__name__] = fn
        return fn

    return decorator


def register_bundle_verb(bundle: str, verb: str):
    """Decorator: register a bundle-scoped verb handler.

    Handlers are NOT part of the public `_DISPATCH` surface. The only way
    in is `agent_call(target_agent_id, verb, **args)` which resolves the
    `bundle` from the target agent and invokes the matching entry here.
    """

    def decorator(fn):
        _BUNDLE_VERBS.setdefault(bundle, {})[verb] = fn
        return fn

    return decorator


def register_tool(name: str = ""):
    """Decorator: register wrapper function to _TOOL_DISPATCH."""

    def decorator(fn):
        _TOOL_DISPATCH[name or fn.__name__] = fn
        return fn

    return decorator


async def dispatch(tool_name: str, **kwargs: Any) -> ToolResult:
    """Call an inner tool function by name, returning a ToolResult.

    Raises KeyError if the tool name is not registered.
    """
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        available = ", ".join(sorted(_DISPATCH.keys()))
        raise KeyError(f"Unknown dispatch tool '{tool_name}'. Available: {available}")
    return await fn(**kwargs)
