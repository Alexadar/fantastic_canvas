"""Fantastic Agent bundle — voice/chat AI agent with persistent history and mic exclusivity."""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import AsyncIterator

from core.dispatch import ToolResult

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

log = logging.getLogger("fantastic_agent")

# ─── AI Backend Connector (stub — real backend TBD) ─────────────


class AiBackendConnector:
    """Swappable connector to AI backend.

    The AI backend (under dev) will:
      - Accept user text + conversation context
      - Proxy to LLM with tool calling
      - Stream response chunks back
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.endpoint = self.config.get("ai_backend_url", "")
        self._conversations: dict[str, list[dict]] = {}

    def get_history(self, agent_id: str) -> list[dict]:
        return self._conversations.setdefault(agent_id, [])

    def add_message(self, agent_id: str, role: str, text: str, mode: str = "voice"):
        history = self.get_history(agent_id)
        history.append({"role": role, "text": text})
        if len(history) > 50:
            self._conversations[agent_id] = history[-50:]
        # Persist to chat.json
        _save_chat_message(agent_id, role, text, mode)

    async def stream_response(
        self, agent_id: str, text: str, mode: str = "voice"
    ) -> AsyncIterator[tuple[str, bool]]:
        """Yield (chunk, is_done) tuples.

        When AI backend is wired:
          - POST to self.endpoint with {text, history, agent_id}
          - Stream SSE/WS chunks back

        Stub: echoes input with simulated delay.
        """
        self.add_message(agent_id, "user", text, mode)

        if self.endpoint:
            # TODO: real AI backend call via httpx streaming
            pass

        # ── Stub response ──
        await asyncio.sleep(0.3)
        response = (
            f'I heard you say: "{text}". '
            "The AI backend is not connected yet — this is an echo stub."
        )
        self.add_message(agent_id, "assistant", response, mode)

        words = response.split()
        chunk_size = 5
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i : i + chunk_size])
            is_last = i + chunk_size >= len(words)
            yield (chunk + (" " if not is_last else ""), is_last)
            if not is_last:
                await asyncio.sleep(0.05)


_connector = AiBackendConnector()
_engine = None

# ─── Mic exclusivity state ──────────────────────────────────────

_mic_owner: str | None = None

# ─── Chat persistence ───────────────────────────────────────────


def _chat_json_path(agent_id: str) -> Path:
    """Return path to .fantastic/agents/{agent_id}/chat.json."""
    base = Path(_engine.project_dir) if _engine and hasattr(_engine, "project_dir") else Path(".")
    return base / ".fantastic" / "agents" / agent_id / "chat.json"


def _save_chat_message(agent_id: str, role: str, text: str, mode: str = "voice"):
    """Append a message to chat.json for the given agent."""
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
    """Load chat history from chat.json."""
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
    """Handle voice/chat transcript from frontend. Streams AI response via broadcast."""
    from core.server import broadcast

    text = text.strip()
    if not text:
        return ToolResult(data={"error": "empty transcript"})

    log.info("voice_transcript agent=%s mode=%s text=%r", agent_id, mode, text[:80])

    # Notify: thinking
    await broadcast({
        "type": "voice_state",
        "agent_id": agent_id,
        "state": "thinking",
    })

    # Stream response chunks via broadcast
    full_response = ""
    try:
        async for chunk, done in _connector.stream_response(agent_id, text, mode):
            full_response += chunk
            await broadcast({
                "type": "voice_response",
                "agent_id": agent_id,
                "text": chunk if not done else full_response,
                "done": done,
            })
    except Exception as exc:
        log.exception("AI connector error for agent=%s", agent_id)
        await broadcast({
            "type": "voice_error",
            "agent_id": agent_id,
            "error": str(exc),
        })

    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_voice_interrupt(agent_id: str = "", **_kw) -> ToolResult:
    """Handle barge-in interrupt from frontend."""
    from core.server import broadcast

    log.info("voice_interrupt agent=%s", agent_id)
    await broadcast({
        "type": "voice_state",
        "agent_id": agent_id,
        "state": "idle",
    })
    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_voice_claim_mic(agent_id: str = "", **_kw) -> ToolResult:
    """Handle mic claim — sets this agent as the exclusive mic owner."""
    from core.server import broadcast

    global _mic_owner
    _mic_owner = agent_id
    log.info("voice_claim_mic agent=%s", agent_id)
    await broadcast({
        "type": "voice_mic_owner",
        "agent_id": agent_id,
    })
    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_voice_release_mic(agent_id: str = "", **_kw) -> ToolResult:
    """Handle mic release — clears mic owner if this agent owns it."""
    from core.server import broadcast

    global _mic_owner
    if _mic_owner == agent_id:
        _mic_owner = None
        log.info("voice_release_mic agent=%s", agent_id)
        await broadcast({
            "type": "voice_mic_owner",
            "agent_id": None,
        })
    return ToolResult(data={"ok": True, "agent_id": agent_id})


async def _handle_chat_history(agent_id: str = "", **_kw) -> ToolResult:
    """Return chat history for an agent."""
    messages = _load_chat_history(agent_id)
    return ToolResult(data={
        "type": "chat_history_response",
        "agent_id": agent_id,
        "messages": messages,
    })


async def _fantastic_agent_configure(ai_backend_url: str = "", **_kw) -> ToolResult:
    """Configure the fantastic agent AI backend connection (inner)."""
    _connector.config["ai_backend_url"] = ai_backend_url
    _connector.endpoint = ai_backend_url
    if ai_backend_url:
        return ToolResult(data={"message": f"Fantastic agent AI backend set to: {ai_backend_url}"})
    return ToolResult(data={"message": "Fantastic agent AI backend reset to echo stub."})


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
    """Return dispatch functions for _DISPATCH table (WS message handlers)."""
    return {
        "get_handbook_fantastic_agent": _get_handbook_fantastic_agent,
        "fantastic_agent_configure": _fantastic_agent_configure,
        "voice_transcript": _handle_voice_transcript,
        "voice_interrupt": _handle_voice_interrupt,
        "voice_claim_mic": _handle_voice_claim_mic,
        "voice_release_mic": _handle_voice_release_mic,
        "chat_history": _handle_chat_history,
    }


def register_tools(engine, fire_broadcasts, process_runner=None):
    """Register fantastic agent user-callable tools."""
    global _engine, _connector
    _engine = engine

    tools = {}

    async def fantastic_agent_configure(ai_backend_url: str = "") -> str:
        """Configure the fantastic agent AI backend connection.

        Args:
            ai_backend_url: URL of the AI backend endpoint.
                           Empty string to reset to echo stub.
        """
        tr = await _fantastic_agent_configure(ai_backend_url=ai_backend_url)
        return tr.data["message"]

    tools["fantastic_agent_configure"] = fantastic_agent_configure

    async def get_handbook_fantastic_agent(skill: str = "") -> str:
        """Get fantastic agent handbook.

        Without arguments: lists available skills.
        With skill name: returns that specific skill doc.

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
