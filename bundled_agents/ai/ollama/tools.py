"""Ollama AI agent bundle — connects to a local Ollama server."""

from __future__ import annotations

import logging

from bundled_agents.ai._shared.ai_dispatch import AiBundleRuntime
from bundled_agents.ai.ollama.provider import OllamaProvider, DEFAULT_ENDPOINT

logger = logging.getLogger(__name__)

NAME = "ollama"


def _provider_factory(agent: dict):
    """Build OllamaProvider from agent config."""
    endpoint = agent.get("endpoint") or DEFAULT_ENDPOINT
    model = agent.get("model") or ""
    ctx_len = agent.get("context_length", 0)
    return OllamaProvider(endpoint=endpoint, model=model, context_length=ctx_len)


_runtime = AiBundleRuntime(NAME, _provider_factory)


def register_dispatch() -> dict:
    return _runtime.make_dispatch_handlers()


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    """Wire to engine + broadcast. No public tools (dispatch-only bundle)."""
    # Resolve the broadcast callable
    from core.bus import bus as _bus

    _runtime.register(engine, _bus.broadcast)
    return {}


async def on_add(project_dir, name: str = "") -> None:
    """Called when `fantastic add ollama` runs. Creates one ollama agent and
    seeds defaults from discovery (endpoint + first available model)."""
    from pathlib import Path as _Path

    from core.agent_store import AgentStore

    store = AgentStore(_Path(project_dir))
    store.init()
    display = name or "main"
    for a in store.list_agents():
        if a.get("bundle") == "ollama" and a.get("display_name") == display:
            print(f"  ollama '{display}' already exists: {a['id']}")
            return

    endpoint = DEFAULT_ENDPOINT
    model = ""
    try:
        result = await OllamaProvider.discover()
        if result.available:
            endpoint = result.endpoint or endpoint
            if result.models:
                model = result.models[0]
                logger.info(
                    "ollama bundle added — discovered %d models at %s",
                    len(result.models),
                    result.endpoint,
                )
    except Exception as e:
        logger.warning("ollama discover failed: %s", e)

    agent = store.create_agent(bundle="ollama")
    meta = {"display_name": display, "endpoint": endpoint}
    if model:
        meta["model"] = model
    store.update_agent_meta(agent["id"], **meta)
    print(f"  ollama '{display}' created: {agent['id']}  model={model or '(none)'}")
