"""AI tools — status, models, model switch, pull."""

from ..dispatch import ToolResult, register_dispatch, register_tool
from ._state import _engine


@register_dispatch("ai_status")
async def _ai_status(**kwargs) -> ToolResult:
    brain = _engine.ai
    status = await brain.status()
    return ToolResult(data=status)


@register_tool("ai_status")
async def ai_status(**kwargs) -> ToolResult:
    return await _ai_status(**kwargs)


@register_dispatch("ai_models")
async def _ai_models(**kwargs) -> ToolResult:
    brain = _engine.ai
    models = await brain.models()
    return ToolResult(data={"models": models})


@register_tool("ai_models")
async def ai_models(**kwargs) -> ToolResult:
    return await _ai_models(**kwargs)


@register_dispatch("ai_model")
async def _ai_model(model: str = "", **kwargs) -> ToolResult:
    brain = _engine.ai
    if not model:
        config = brain.provider
        current = config.model if config else "none"
        return ToolResult(data={"model": current})
    await brain.set_model(model)
    return ToolResult(data={"model": model, "status": "set"})


@register_tool("ai_model")
async def ai_model(**kwargs) -> ToolResult:
    return await _ai_model(**kwargs)


@register_dispatch("ai_pull")
async def _ai_pull(model: str, **kwargs) -> ToolResult:
    brain = _engine.ai
    await brain.pull_model(model)
    return ToolResult(data={"model": model, "status": "pulled"})


@register_tool("ai_pull")
async def ai_pull(**kwargs) -> ToolResult:
    return await _ai_pull(**kwargs)
