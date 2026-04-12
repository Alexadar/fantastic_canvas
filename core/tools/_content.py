"""Content tools — aliases and project file operations."""

import os
import secrets
from pathlib import Path

from ..dispatch import ToolResult, register_dispatch, register_tool
from . import _state


@register_dispatch("content_alias_file")
async def _content_alias_file(file_path: str, persistent: bool = True) -> ToolResult:
    alias_id = secrets.token_hex(4)
    abs_path = os.path.abspath(file_path)
    try:
        rel = os.path.relpath(abs_path, str(_state._engine.project_dir))
        if not rel.startswith(".."):
            _state._engine.add_content_alias(
                alias_id,
                {
                    "type": "file",
                    "path": rel,
                    "relative": True,
                    "persistent": persistent,
                },
            )
        else:
            _state._engine.add_content_alias(
                alias_id, {"type": "file", "path": abs_path, "persistent": persistent}
            )
    except ValueError:
        _state._engine.add_content_alias(
            alias_id, {"type": "file", "path": abs_path, "persistent": persistent}
        )
    return ToolResult(data={"alias_path": f"/content/{alias_id}", "alias_id": alias_id})


@register_tool("content_alias_file")
async def content_alias_file(file_path: str, persistent: bool = True) -> str:
    """Create a URL alias for a local file. Returns the alias path to use in HTML (e.g. in <img src="...">).

    Args:
        file_path: Absolute or relative path to the file to serve.
        persistent: If True, alias survives server restart. Default True.
    """
    tr = await _content_alias_file(file_path, persistent)
    return tr.data["alias_path"]


@register_dispatch("content_alias_url")
async def _content_alias_url(url: str, persistent: bool = True) -> ToolResult:
    alias_id = secrets.token_hex(4)
    _state._engine.add_content_alias(
        alias_id, {"type": "url", "url": url, "persistent": persistent}
    )
    return ToolResult(data={"alias_path": f"/content/{alias_id}", "alias_id": alias_id})


@register_tool("content_alias_url")
async def content_alias_url(url: str, persistent: bool = True) -> str:
    """Create a URL alias that redirects to the given URL. Returns the alias path to use in HTML.

    Args:
        url: The URL to redirect to.
        persistent: If True, alias survives server restart. Default True.
    """
    tr = await _content_alias_url(url, persistent)
    return tr.data["alias_path"]


@register_dispatch("get_aliases")
async def _get_aliases() -> ToolResult:
    aliases = _state._engine.content_aliases
    result = []
    for alias_id, entry in aliases.items():
        info = {
            "alias_id": alias_id,
            "alias_path": f"/content/{alias_id}",
            "type": entry["type"],
            "persistent": entry.get("persistent", False),
        }
        if entry["type"] == "file":
            info["path"] = entry["path"]
            info["relative"] = entry.get("relative", False)
        elif entry["type"] == "url":
            info["url"] = entry["url"]
        result.append(info)
    return ToolResult(data={"aliases": result})


@register_tool("get_aliases")
async def get_aliases() -> list[dict]:
    """List all content aliases with their paths and persistence flags."""
    tr = await _get_aliases()
    return tr.data["aliases"]


# ─── Project file operations ─────────────────────────────────────


def _resolve_safe(file_path: str) -> Path:
    """Resolve a relative path within the project dir. Raises ValueError on escape."""
    project_dir = Path(_state._engine.project_dir).resolve()
    resolved = (project_dir / file_path).resolve()
    resolved.relative_to(project_dir)  # raises ValueError if outside
    return resolved


@register_dispatch("list_files")
async def _list_files(path: str = "") -> ToolResult:
    files = _state._engine.list_files()
    if path:
        # Walk tree to find the requested subtree
        parts = Path(path).parts
        node = files
        for part in parts:
            match = next((f for f in node if f["name"] == part and f.get("isDir")), None)
            if match is None:
                return ToolResult(data={"error": f"Directory not found: {path}"})
            node = match.get("children", [])
        files = node
    return ToolResult(data={"files": files})


@register_tool("list_files")
async def list_files(path: str = "") -> list[dict]:
    """List project files. Optionally filter by subdirectory path.

    Args:
        path: Subdirectory to list (relative). Empty = project root.
    """
    tr = await _list_files(path=path)
    if "error" in tr.data:
        return [tr.data]
    return tr.data["files"]


@register_dispatch("read_file")
async def _read_file(path: str = "") -> ToolResult:
    if not path:
        return ToolResult(data={"error": "path is required"})
    try:
        resolved = _resolve_safe(path)
    except ValueError:
        return ToolResult(data={"error": f"Path outside project: {path}"})
    if not resolved.exists():
        return ToolResult(data={"error": f"File not found: {path}"})
    if resolved.is_dir():
        return ToolResult(data={"error": f"Path is a directory: {path}"})
    try:
        content = resolved.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(data={"error": f"Binary file, cannot read as text: {path}"})
    return ToolResult(data={"path": path, "content": content})


@register_tool("read_file")
async def read_file(path: str) -> dict:
    """Read a text file from the project directory.

    Args:
        path: Relative path to the file (e.g. "scripts/run.py").
    """
    tr = await _read_file(path=path)
    return tr.data


@register_dispatch("write_file")
async def _write_file(
    path: str = "", content: str = "", agent_id: str = ""
) -> ToolResult:
    if not path:
        return ToolResult(data={"error": "path is required"})
    # If path has no directory and agent_id is given, scope to agent folder
    if agent_id and "/" not in path and "\\" not in path:
        path = f".fantastic/agents/{agent_id}/{path}"
    try:
        resolved = _resolve_safe(path)
    except ValueError:
        return ToolResult(data={"error": f"Path outside project: {path}"})
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content, encoding="utf-8")
    return ToolResult(data={"path": path, "written": True})


@register_tool("write_file")
async def write_file(path: str, content: str, agent_id: str = "") -> dict:
    """Write content to a file in the project directory. Creates parent directories as needed.

    If agent_id is provided and path is a bare filename (no directory), the file is
    written to the agent's own folder (.fantastic/agents/{agent_id}/) to avoid polluting
    the project root.

    Args:
        path: Relative path to the file (e.g. "steps/01_load.py"). Bare filenames are scoped to agent folder when agent_id is set.
        content: The text content to write.
        agent_id: Optional agent ID. When set, bare filenames go to the agent's folder.
    """
    tr = await _write_file(path=path, content=content, agent_id=agent_id)
    return tr.data
