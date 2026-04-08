"""Convert Fantastic tool schemas to Ollama tool format."""

_cached_tools: list[dict] | None = None


def build_ollama_tools(exclude_prefixes: tuple[str, ...] = ("ai_",)) -> list[dict]:
    """Convert _TOOL_DISPATCH schemas to Ollama tool definitions.

    Caches result — tools don't change at runtime after init.
    Excludes ai_* tools to prevent self-modification.
    """
    global _cached_tools
    if _cached_tools is not None:
        return _cached_tools

    from core.server._rest import build_schema

    schema = build_schema()
    tools = []
    for t in schema["tools"]:
        if any(t["name"].startswith(p) for p in exclude_prefixes):
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
        )
    _cached_tools = tools
    return tools
