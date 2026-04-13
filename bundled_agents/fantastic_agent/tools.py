"""fantastic_agent — UI-only bundle that fronts any AI backend.

Stores config in agent.json:
    upstream_agent_id: the AI agent to chat with
    upstream_bundle:   bundle name (ollama/openai/anthropic/integrated)

The frontend (web/index.html) uses the injected `fantastic_transport()` global
to `watch()` the upstream agent's events and call its `{bundle}_send` dispatch.
This bundle has no HTTP/WS coupling — core orchestrates, transport does the rest.
"""

from __future__ import annotations

import logging

from bundled_agents.ai._shared.chat_storage import load_history, save_message
from core.dispatch import ToolResult, register_dispatch, register_tool

logger = logging.getLogger(__name__)

NAME = "fantastic_agent"

_engine = None


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    global _engine
    _engine = engine
    return {}


@register_dispatch("fantastic_agent_get_config")
async def _get_config(agent_id: str = "", **_kw) -> ToolResult:
    if not agent_id:
        return ToolResult(data={"error": "agent_id required"})
    agent = _engine.get_agent(agent_id)
    if not agent:
        return ToolResult(data={"error": f"Agent {agent_id} not found"})
    return ToolResult(
        data={
            "upstream_agent_id": agent.get("upstream_agent_id", ""),
            "upstream_bundle": agent.get("upstream_bundle", ""),
        }
    )


@register_dispatch("fantastic_agent_configure")
async def _configure(
    agent_id: str = "",
    upstream_agent_id: str = "",
    upstream_bundle: str = "",
    **_kw,
) -> ToolResult:
    if not agent_id:
        return ToolResult(data={"error": "agent_id required"})
    updates: dict = {}
    if upstream_agent_id:
        updates["upstream_agent_id"] = upstream_agent_id
    if upstream_bundle:
        updates["upstream_bundle"] = upstream_bundle
    if not updates:
        return ToolResult(data={"error": "nothing to update"})
    _engine.update_agent_meta(agent_id, **updates)
    return ToolResult(
        data={"ok": True, "agent_id": agent_id, **updates},
        broadcast=[{"type": "agent_updated", "agent_id": agent_id, **updates}],
    )


@register_dispatch("fantastic_agent_save_message")
async def _save_msg(
    agent_id: str = "",
    role: str = "user",
    text: str = "",
    mode: str = "chat",
    **_kw,
) -> ToolResult:
    if not agent_id or not text:
        return ToolResult(data={"error": "agent_id and text required"})
    msg = save_message(_engine.project_dir, agent_id, role, text, mode)
    return ToolResult(data={"ok": True, "message": msg})


@register_dispatch("fantastic_agent_history")
async def _history(agent_id: str = "", **_kw) -> ToolResult:
    msgs = load_history(_engine.project_dir, agent_id)
    return ToolResult(
        data={"ok": True},
        reply=[
            {
                "type": "fantastic_agent_history_response",
                "agent_id": agent_id,
                "messages": msgs,
            }
        ],
    )


@register_tool("fantastic_agent_configure")
async def fantastic_agent_configure(
    agent_id: str, upstream_agent_id: str = "", upstream_bundle: str = ""
) -> dict:
    """Set the upstream AI agent this fantastic_agent chats with.

    Args:
        agent_id: This fantastic_agent's ID.
        upstream_agent_id: ID of the target AI agent (ollama/openai/etc.).
        upstream_bundle: Bundle name of upstream (e.g. "ollama").
    """
    tr = await _configure(
        agent_id=agent_id,
        upstream_agent_id=upstream_agent_id,
        upstream_bundle=upstream_bundle,
    )
    return tr.data


async def on_add(project_dir, name: str = "") -> None:
    """Create one fantastic_agent UI-proxy agent. Upstream must be configured
    afterwards via `@<fa_id> fantastic_agent_configure upstream_agent_id=... upstream_bundle=...`.
    """
    from pathlib import Path as _Path

    from core.agent_store import AgentStore

    store = AgentStore(_Path(project_dir))
    store.init()
    display = name or "main"
    for a in store.list_agents():
        if a.get("bundle") == "fantastic_agent" and a.get("display_name") == display:
            print(f"  fantastic_agent '{display}' already exists: {a['id']}")
            return
    agent = store.create_agent(bundle="fantastic_agent")
    store.update_agent_meta(agent["id"], display_name=display)
    print(f"  fantastic_agent '{display}' created: {agent['id']}")
    logger.info("fantastic_agent bundle added")


async def cli_sync(agent_id: str, text: str) -> str:
    """Sync CLI entry: route to configured upstream AI agent, save to chat.json."""
    from core.dispatch import _DISPATCH

    agent = _engine.get_agent(agent_id)
    if not agent:
        return f"[error] agent {agent_id} not found"
    upstream_id = agent.get("upstream_agent_id", "")
    upstream_bundle = agent.get("upstream_bundle", "")
    if not upstream_id or not upstream_bundle:
        return (
            "[fantastic_agent] not configured — set upstream_agent_id + upstream_bundle"
        )

    save_message(_engine.project_dir, agent_id, "user", text)

    handler = _DISPATCH.get(f"{upstream_bundle}_send")
    if not handler:
        return f"[error] no {upstream_bundle}_send handler"

    result = await handler(agent_id=upstream_id, text=text)
    reply = ""
    if isinstance(result, ToolResult) and isinstance(result.data, dict):
        reply = result.data.get("response") or result.data.get("error") or ""

    if reply:
        save_message(_engine.project_dir, agent_id, "assistant", reply)
    return reply
