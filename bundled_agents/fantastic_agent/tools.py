"""Fantastic Agent bundle — voice/chat AI agent with persistent history and mic exclusivity."""

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
                    {"function": {"name": tc["name"], "arguments": tc["arguments"]}}
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

    # Save AI response
    if full_response:
        _save_chat_message(agent_id, "assistant", full_response, mode)

    return ToolResult(data={"ok": True, "agent_id": agent_id})


def _build_messages_from_history(agent_id: str, current_text: str) -> list[dict]:
    """Build LLM messages from chat history + current input."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful AI assistant in the Fantastic Canvas environment. "
                "You have access to tools for creating agents, executing code, managing the canvas, "
                "and more. Use tools when the user's request requires taking actions."
            ),
        }
    ]
    # Recent history
    history = _load_chat_history(agent_id)
    for msg in history[-20:]:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("text", "")})
    # Current input
    messages.append({"role": "user", "content": current_text})
    return messages


async def _handle_voice_interrupt(agent_id: str = "", **_kw) -> ToolResult:
    from core.server import broadcast
    log.info("voice_interrupt agent=%s", agent_id)
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
    return ToolResult(data={
        "type": "chat_history_response",
        "agent_id": agent_id,
        "messages": messages,
    })


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
