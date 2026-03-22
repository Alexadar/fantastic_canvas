"""AI tools — status, models, model switch, pull, stop, start, swap, configure."""

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


@register_dispatch("ai_stop")
async def _ai_stop(**kwargs) -> ToolResult:
    brain = _engine.ai
    result = await brain.stop_provider()
    return ToolResult(data={"status": result})


@register_tool("ai_stop")
async def ai_stop(**kwargs) -> ToolResult:
    return await _ai_stop(**kwargs)


@register_dispatch("ai_start")
async def _ai_start(**kwargs) -> ToolResult:
    brain = _engine.ai
    result = await brain.start_provider()
    return ToolResult(data={"status": result})


@register_tool("ai_start")
async def ai_start(**kwargs) -> ToolResult:
    return await _ai_start(**kwargs)


@register_dispatch("ai_swap")
async def _ai_swap(provider: str, model: str = "", **kwargs) -> ToolResult:
    brain = _engine.ai
    result = await brain.swap_provider(provider, model or None)
    return ToolResult(data={"status": result})


@register_tool("ai_swap")
async def ai_swap(**kwargs) -> ToolResult:
    return await _ai_swap(**kwargs)


@register_dispatch("ai_configure")
async def _ai_configure(**kwargs) -> ToolResult:
    brain = _engine.ai
    result = await brain.configure()
    return ToolResult(data={"status": result})


@register_tool("ai_configure")
async def ai_configure(**kwargs) -> ToolResult:
    return await _ai_configure(**kwargs)


@register_dispatch("ai_providers")
async def _ai_providers(**kwargs) -> ToolResult:
    from ..ai.brain import AIBrain
    providers = AIBrain.available_providers()
    return ToolResult(data={"providers": providers})


@register_tool("ai_providers")
async def ai_providers(**kwargs) -> ToolResult:
    return await _ai_providers(**kwargs)
