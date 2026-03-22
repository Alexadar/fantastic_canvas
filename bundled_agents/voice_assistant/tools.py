"""Voice Assistant bundle — always-on voice agent with STT/TTS and AI backend connector."""

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator

from core.dispatch import ToolResult

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"

log = logging.getLogger("voice_assistant")

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

    def add_message(self, agent_id: str, role: str, text: str):
        history = self.get_history(agent_id)
        history.append({"role": role, "text": text})
        if len(history) > 50:
            self._conversations[agent_id] = history[-50:]

    async def stream_response(
        self, agent_id: str, text: str
    ) -> AsyncIterator[tuple[str, bool]]:
        """Yield (chunk, is_done) tuples.

        When AI backend is wired:
          - POST to self.endpoint with {text, history, agent_id}
          - Stream SSE/WS chunks back

        Stub: echoes input with simulated delay.
        """
        self.add_message(agent_id, "user", text)

        if self.endpoint:
            # TODO: real AI backend call via httpx streaming
            pass

        # ── Stub response ──
        await asyncio.sleep(0.3)
        response = (
            f'I heard you say: "{text}". '
            "The AI backend is not connected yet — this is an echo stub."
        )
        self.add_message(agent_id, "assistant", response)

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


# ─── Dispatch handlers (registered into _DISPATCH) ──────────────


async def _handle_voice_transcript(agent_id: str = "", text: str = "", **_kw) -> ToolResult:
    """Handle voice transcript from frontend. Streams AI response via broadcast."""
    from core.server import broadcast

    text = text.strip()
    if not text:
        return ToolResult(data={"error": "empty transcript"})

    log.info("voice_transcript agent=%s text=%r", agent_id, text[:80])

    # Notify: thinking
    await broadcast({
        "type": "voice_state",
        "agent_id": agent_id,
        "state": "thinking",
    })

    # Stream response chunks via broadcast
    full_response = ""
    try:
        async for chunk, done in _connector.stream_response(agent_id, text):
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


# ─── Handbook ────────────────────────────────────────────────────


async def _get_handbook_voice_assistant(skill: str = "", **_kw) -> ToolResult:
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
            "text": "Voice assistant skills: " + ", ".join(available)
            if available
            else "No voice assistant skills found."
        }
    )


# ─── Bundle Registration ────────────────────────────────────────


def register_dispatch():
    """Return dispatch functions for _DISPATCH table (WS message handlers)."""
    return {
        "get_handbook_voice_assistant": _get_handbook_voice_assistant,
        "voice_transcript": _handle_voice_transcript,
        "voice_interrupt": _handle_voice_interrupt,
    }


def register_tools(engine, fire_broadcasts, process_runner=None):
    """Register voice assistant user-callable tools."""
    global _engine, _connector
    _engine = engine

    tools = {}

    async def voice_configure(ai_backend_url: str = "") -> str:
        """Configure the voice assistant AI backend connection.

        Args:
            ai_backend_url: URL of the AI backend endpoint.
                           Empty string to reset to echo stub.
        """
        _connector.config["ai_backend_url"] = ai_backend_url
        _connector.endpoint = ai_backend_url
        if ai_backend_url:
            return f"Voice assistant AI backend set to: {ai_backend_url}"
        return "Voice assistant AI backend reset to echo stub."

    tools["voice_configure"] = voice_configure

    async def get_handbook_voice_assistant(skill: str = "") -> str:
        """Get voice assistant handbook.

        Without arguments: lists available skills.
        With skill name: returns that specific skill doc.

        Available skills: voice-assistant

        Examples:
            get_handbook_voice_assistant()
            get_handbook_voice_assistant(skill="voice-assistant")
        """
        tr = await _get_handbook_voice_assistant(skill)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return tr.data["text"]

    tools["get_handbook_voice_assistant"] = get_handbook_voice_assistant

    return tools
