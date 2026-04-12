"""Fantastic Agent bundle — voice/chat AI agent with persistent history and mic exclusivity."""

import asyncio
import json
import logging
import time
from pathlib import Path

from core.dispatch import ToolResult
from core.ai.provider import GenerationResult
from core.ai.tool_schema import build_ollama_tools

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

log = logging.getLogger("fantastic_agent")

_engine = None

# ─── Per-agent concurrency control ─────────────────────────────

_agent_locks: dict[str, asyncio.Lock] = {}
_agent_abort: dict[str, bool] = {}

# ─── Mic exclusivity state ──────────────────────────────────────

_mic_owner: str | None = None

# ─── Chat persistence ───────────────────────────────────────────


def _chat_json_path(agent_id: str) -> Path:
    base = Path(_engine.project_dir) if _engine and hasattr(_engine, "project_dir") else Path(".")
    return base / ".fantastic" / "agents" / agent_id / "chat.json"


def _save_chat_message(agent_id: str, role: str, text: str, mode: str = "voice"):
    path = _chat_json_path(agent_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"messages": []}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {"messages": []}
        data["messages"].append({
            "role": role,
            "text": text,
            "ts": int(time.time()),
            "mode": mode,
        })
        path.write_text(json.dumps(data, indent=2))
    except OSError as exc:
        log.warning("Failed to save chat message for agent=%s: %s", agent_id, exc)


def _load_chat_history(agent_id: str) -> list[dict]:
    path = _chat_json_path(agent_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data.get("messages", [])
    except (json.JSONDecodeError, OSError):
        return []


# ─── Dispatch handlers (registered into _DISPATCH) ──────────────


async def _handle_voice_transcript(agent_id: str = "", text: str = "", mode: str = "voice", **_kw) -> ToolResult:
    """Handle voice/chat transcript. Streams AI response via broadcast with tool calling."""
    from core.server import broadcast

    text = text.strip()
    if not text:
        return ToolResult(data={"error": "empty transcript"})

    log.info("voice_transcript agent=%s mode=%s text=%r", agent_id, mode, text[:80])

    # Per-agent lock — reject if already processing
    lock = _agent_locks.setdefault(agent_id, asyncio.Lock())
    if lock.locked():
        await broadcast({"type": "voice_error", "agent_id": agent_id, "error": "busy"})
        return ToolResult(data={"error": "busy"})

    async with lock:
        return await _handle_voice_transcript_inner(agent_id, text, mode, broadcast)


async def _handle_voice_transcript_inner(agent_id: str, text: str, mode: str, broadcast) -> ToolResult:
    """Inner handler — runs under per-agent lock."""
    # Clear abort flag
    _agent_abort[agent_id] = False

    # Save user message
    _save_chat_message(agent_id, "user", text, mode)

    # Check AI brain available
    brain = _engine.ai if _engine else None
    if not brain:
        await broadcast({"type": "voice_error", "agent_id": agent_id, "error": "AI brain not available"})
        return ToolResult(data={"error": "AI brain not available"})

    provider = await brain.ensure_provider()
    if not provider:
        msg = brain._no_provider_message()
        await broadcast({"type": "voice_error", "agent_id": agent_id, "error": msg})
        return ToolResult(data={"error": msg})

    # Build messages from chat history
    messages = _build_messages_from_history(agent_id, text)
    tools = build_ollama_tools()

    # Notify: thinking
    await broadcast({"type": "voice_state", "agent_id": agent_id, "state": "thinking"})

    full_response = ""
    in_think = False
    max_rounds = 20

    try:
        for _ in range(max_rounds):
            result: GenerationResult | None = None
            async for token in provider.generate_with_tools(messages, tools):
                # Check abort flag (set by voice_interrupt)
                if _agent_abort.get(agent_id):
                    _agent_abort[agent_id] = False
                    break
                if isinstance(token, GenerationResult):
                    result = token
                else:
                    # Handle <think> blocks — stream state, skip content
                    if "<think>" in token:
                        in_think = True
                        continue
                    if "</think>" in token:
                        in_think = False
                        await broadcast({"type": "voice_state", "agent_id": agent_id, "state": "responding"})
                        continue
                    if in_think:
                        continue

                    full_response += token
                    await broadcast({
                        "type": "voice_response",
                        "agent_id": agent_id,
                        "text": token,
                        "done": False,
                    })

            if result is None or not result.tool_calls:
                break

            # Execute tool calls
            messages.append({
                "role": "assistant",
                "content": result.text,
                "tool_calls": [
                    {"type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for tc in result.tool_calls
                ],
            })

            for tc in result.tool_calls:
                tool_result = await brain._execute_tool(tc["name"], tc["arguments"])
                messages.append({"role": "tool", "content": tool_result})

                # Broadcast tool activity
                await broadcast({
                    "type": "voice_response",
                    "agent_id": agent_id,
                    "text": f"\n[tool: {tc['name']}]\n",
                    "done": False,
                })

    except Exception as exc:
        log.exception("AI error for agent=%s", agent_id)
        await broadcast({"type": "voice_error", "agent_id": agent_id, "error": str(exc)})

    # Final done signal
    await broadcast({
        "type": "voice_response",
        "agent_id": agent_id,
        "text": full_response,
        "done": True,
    })
    await broadcast({"type": "voice_state", "agent_id": agent_id, "state": "idle"})

    # Broadcast context usage + schedule info
    ctx_used = sum(len(m.get("content", "")) for m in messages) // 4
    ctx_max = 0
    if brain and brain.provider and hasattr(brain.provider, "context_length"):
        ctx_max = brain.provider.context_length
    from core.tools._state import _scheduler
    schedules = _scheduler.list_for_agent(agent_id) if _scheduler else []
    await broadcast({
        "type": "context_usage",
        "agent_id": agent_id,
        "used": ctx_used,
        "max": ctx_max,
        "provider": str(brain.provider) if brain and brain.provider else None,
        "provider_online": brain.provider is not None if brain else False,
        "schedules": len(schedules),
        "total_runs": sum(s.get("run_count", 0) for s in schedules),
    })

    # Save AI response
    if full_response:
        _save_chat_message(agent_id, "assistant", full_response, mode)

    return ToolResult(data={"ok": True, "agent_id": agent_id})


def _get_context_budget() -> int:
    """Get token budget from the AI brain's provider."""
    brain = _engine.ai if _engine else None
    if brain and brain.provider and hasattr(brain.provider, "context_length"):
        ctx = brain.provider.context_length
        if ctx:
            return ctx - 2048
    return 8192 - 2048  # default


def _build_messages_from_history(agent_id: str, current_text: str) -> list[dict]:
    """Build LLM messages from chat history + budget-aware truncation."""
    budget = _get_context_budget()

    system_msg = {
        "role": "system",
        "content": (
            "You are a helpful AI assistant in the Fantastic Canvas environment. "
            "You have access to tools for creating agents, executing code, managing the canvas, "
            "and more. Use tools when the user's request requires taking actions. "
            "IMPORTANT: Never spawn cascades of fantastic_agent agents — you cannot communicate with them programmatically. "
            "If unsure whether to create agents or run code autonomously, ask the user first. "
            "When creating files, write them to the agent's own folder (.fantastic/agents/{agent_id}/) unless the user specifies a project path. "
            "This keeps the project directory clean."
        ),
    }
    user_msg = {"role": "user", "content": current_text}
    used = (len(system_msg["content"]) + len(current_text)) // 4

    # Fill remaining budget with history (newest first)
    history = _load_chat_history(agent_id)
    history_msgs: list[dict] = []
    for msg in reversed(history):
        role = msg.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        text = msg.get("text", "")
        cost = len(text) // 4
        if used + cost > budget:
            break
        history_msgs.append({"role": role, "content": text})
        used += cost

    return [system_msg] + list(reversed(history_msgs)) + [user_msg]


async def _handle_voice_interrupt(agent_id: str = "", **_kw) -> ToolResult:
    from core.server import broadcast
    log.info("voice_interrupt agent=%s", agent_id)
    _agent_abort[agent_id] = True
    await broadcast({"type": "voice_state", "agent_id": agent_id, "state": "idle"})
    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_voice_claim_mic(agent_id: str = "", **_kw) -> ToolResult:
    from core.server import broadcast
    global _mic_owner
    _mic_owner = agent_id
    log.info("voice_claim_mic agent=%s", agent_id)
    await broadcast({"type": "voice_mic_owner", "agent_id": agent_id})
    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_voice_release_mic(agent_id: str = "", **_kw) -> ToolResult:
    from core.server import broadcast
    global _mic_owner
    if _mic_owner == agent_id:
        _mic_owner = None
        log.info("voice_release_mic agent=%s", agent_id)
        await broadcast({"type": "voice_mic_owner", "agent_id": None})
    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_chat_history(agent_id: str = "", **_kw) -> ToolResult:
    messages = _load_chat_history(agent_id)
    return ToolResult(
        data={"ok": True},
        reply=[{
            "type": "chat_history_response",
            "agent_id": agent_id,
            "messages": messages,
        }],
    )


# ─── Handbook ────────────────────────────────────────────────────


async def _get_handbook_fantastic_agent(skill: str = "", **_kw) -> ToolResult:
    if skill:
        skill_file = _SKILLS_DIR / f"{skill}.md"
        if skill_file.exists():
            return ToolResult(data={"text": f"# SKILL: {skill}\n\n{skill_file.read_text()}"})
        available = [p.stem for p in _SKILLS_DIR.glob("*.md")] if _SKILLS_DIR.exists() else []
        avail_str = ", ".join(sorted(available)) or "(none)"
        return ToolResult(data={"error": f"Skill '{skill}' not found. Available: {avail_str}"})
    available = sorted(p.stem for p in _SKILLS_DIR.glob("*.md")) if _SKILLS_DIR.exists() else []
    return ToolResult(
        data={
            "text": "Fantastic agent skills: " + ", ".join(available)
            if available
            else "No fantastic agent skills found."
        }
    )


# ─── Bundle Registration ────────────────────────────────────────


def register_dispatch():
    return {
        "get_handbook_fantastic_agent": _get_handbook_fantastic_agent,
        "voice_transcript": _handle_voice_transcript,
        "voice_interrupt": _handle_voice_interrupt,
        "voice_claim_mic": _handle_voice_claim_mic,
        "voice_release_mic": _handle_voice_release_mic,
        "chat_history": _handle_chat_history,
    }


def register_tools(engine, fire_broadcasts, process_runner=None):
    global _engine
    _engine = engine

    tools = {}

    async def get_handbook_fantastic_agent(skill: str = "") -> str:
        """Get fantastic agent handbook.

        Available skills: fantastic-agent

        Examples:
            get_handbook_fantastic_agent()
            get_handbook_fantastic_agent(skill="fantastic-agent")
        """
        tr = await _get_handbook_fantastic_agent(skill)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return tr.data["text"]

    tools["get_handbook_fantastic_agent"] = get_handbook_fantastic_agent

    return tools
