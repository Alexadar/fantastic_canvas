"""AI config — load/save from .fantastic/ai/config.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _config_path(project_dir: Path) -> Path:
    return project_dir / ".fantastic" / "ai" / "config.json"


def load_config(project_dir: Path) -> dict[str, Any] | None:
    """Load AI config, or None if not configured."""
    path = _config_path(project_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_config(project_dir: Path, config: dict[str, Any]) -> None:
    """Save AI config to .fantastic/ai/config.json."""
    path = _config_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))
