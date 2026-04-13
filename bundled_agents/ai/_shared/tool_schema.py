"""Build OpenAI-format tool schemas from _TOOL_DISPATCH registry."""

from __future__ import annotations

import inspect
from functools import lru_cache
from typing import Any

from core.dispatch import _TOOL_DISPATCH


@lru_cache(maxsize=1)
def build_tool_schema(
    exclude_prefixes: tuple[str, ...] = ("ai_",),
) -> list[dict]:
    """Build OpenAI function schema from registered tools.

    Returns a list of {"type": "function", "function": {"name", "description", "parameters"}}.
    """
    tools: list[dict] = []
    for name, fn in _TOOL_DISPATCH.items():
        if any(name.startswith(p) for p in exclude_prefixes):
            continue
        # Skip bundle-specific AI dispatch tools (they're not for AI-to-AI use)
        if (
            name.endswith("_send")
            or name.endswith("_interrupt")
            or name.endswith("_save_message")
            or name.endswith("_history")
            or name.endswith("_configure")
        ):
            continue
        desc = (fn.__doc__ or "").strip().split("\n")[0] or name
        params = _build_params(fn)
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": params,
                },
            }
        )
    return tools


def _build_params(fn: Any) -> dict:
    """Introspect function signature into JSON Schema."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return {"type": "object", "properties": {}}

    properties: dict = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "kwargs", "args"):
            continue
        schema = {"type": "string"}
        if param.annotation is int:
            schema["type"] = "integer"
        elif param.annotation is bool:
            schema["type"] = "boolean"
        elif param.annotation is float:
            schema["type"] = "number"
        elif param.annotation is dict:
            schema["type"] = "object"
        elif param.annotation is list:
            schema["type"] = "array"
        properties[name] = schema
        if param.default is inspect.Parameter.empty:
            required.append(name)

    result: dict = {"type": "object", "properties": properties}
    if required:
        result["required"] = required
    return result
