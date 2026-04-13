"""Per-agent chat persistence — UI-triggered, never automatic."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _chat_path(project_dir: Path, agent_id: str) -> Path:
    return Path(project_dir) / ".fantastic" / "agents" / agent_id / "chat.json"


def save_message(
    project_dir: Path, agent_id: str, role: str, text: str, mode: str = "chat"
) -> dict:
    """Append a message to the agent's chat.json. Returns the saved message."""
    path = _chat_path(project_dir, agent_id)
    msg = {"role": role, "text": text, "ts": int(time.time()), "mode": mode}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"messages": []}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {"messages": []}
        data["messages"].append(msg)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to save chat message for %s: %s", agent_id, e)
    return msg


def load_history(project_dir: Path, agent_id: str) -> list[dict]:
    """Load all messages from the agent's chat.json."""
    path = _chat_path(project_dir, agent_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("messages", [])
    except (json.JSONDecodeError, OSError):
        return []
