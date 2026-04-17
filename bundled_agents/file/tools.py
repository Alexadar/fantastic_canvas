"""file bundle — a filesystem root as an agent.

One agent per filesystem root. Each agent's `agent.json` stores:

    root      : absolute path ("" → project_dir)
    readonly  : refuse write/delete/rename/mkdir when True
    hidden    : list of names to exclude from listings

Callers use `agent_call(target, verb, **args)` exclusively. Verbs:
`list`, `read`, `write`, `delete`, `rename`, `mkdir`. Handlers are
registered as `file_{verb}` so `agent_call` → `{bundle}_{verb}` resolves
them.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from core.dispatch import ToolResult, register_dispatch

logger = logging.getLogger(__name__)

NAME = "file"

_engine = None

DEFAULT_HIDDEN = [
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".eggs",
    "*.egg-info",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    ".next",
    ".nuxt",
    ".fantastic",
]


def register_tools(engine, fire_broadcasts, process_runner=None) -> dict:
    global _engine
    _engine = engine
    return {}


# ─── helpers ────────────────────────────────────────────────────────


def _agent_root(agent: dict) -> Path:
    """Return the absolute root Path for a file agent. Empty root → project_dir."""
    root = agent.get("root") or ""
    if not root:
        return Path(_engine.project_dir).resolve()
    return Path(root).expanduser().resolve()


def _resolve_safe(root: Path, rel_path: str) -> Path:
    """Resolve `root/rel_path` and raise ValueError if it escapes root."""
    target = (root / rel_path).resolve() if rel_path else root
    target.relative_to(root)  # raises ValueError on escape
    return target


def _hidden_set(agent: dict) -> set[str]:
    raw = agent.get("hidden")
    if raw is None:
        raw = DEFAULT_HIDDEN
    return set(raw)


def _walk(dirpath: Path, root: Path, hidden: set[str]) -> list[dict]:
    entries: list[dict] = []
    try:
        items = sorted(
            dirpath.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
        )
    except PermissionError:
        return entries
    for item in items:
        if item.name in hidden:
            continue
        rel = str(item.relative_to(root))
        if item.is_dir():
            entries.append(
                {
                    "name": item.name,
                    "path": rel,
                    "isDir": True,
                    "children": _walk(item, root, hidden),
                }
            )
        else:
            entries.append({"name": item.name, "path": rel, "isDir": False})
    return entries


def _get_agent_or_error(agent_id: str) -> tuple[dict | None, ToolResult | None]:
    if not agent_id:
        return None, ToolResult(data={"error": "agent_id required"})
    agent = _engine.get_agent(agent_id)
    if not agent or agent.get("bundle") != "file":
        return None, ToolResult(data={"error": f"{agent_id} is not a file agent"})
    return agent, None


def _readonly_error(agent: dict) -> ToolResult | None:
    if agent.get("readonly"):
        return ToolResult(data={"error": "readonly"})
    return None


# ─── bundle setup ───────────────────────────────────────────────────


async def on_add(
    project_dir,
    name: str = "",
    root: str = "",
    readonly: bool = False,
    hidden: list[str] | None = None,
) -> None:
    """Create ONE file-root agent. Explicit command only (never auto)."""
    from core.agent_store import AgentStore

    store = AgentStore(Path(project_dir))
    store.init()
    display = name or "project"

    for a in store.list_agents():
        if a.get("bundle") == "file" and a.get("display_name") == display:
            print(f"  file '{display}' already exists: {a['id']}")
            return

    agent = store.create_agent(bundle="file")
    meta: dict = {
        "display_name": display,
        "root": root,
        "readonly": bool(readonly),
    }
    if hidden is not None:
        meta["hidden"] = hidden
    store.update_agent_meta(agent["id"], **meta)
    shown_root = root or "(project_dir)"
    print(f"  file '{display}' created: {agent['id']}  root={shown_root}")


# ─── verb handlers ──────────────────────────────────────────────────


@register_dispatch("file_list")
async def _list(agent_id: str = "", path: str = "", **_kw) -> ToolResult:
    agent, err = _get_agent_or_error(agent_id)
    if err:
        return err
    root = _agent_root(agent)
    try:
        target = _resolve_safe(root, path)
    except ValueError:
        return ToolResult(data={"error": f"path outside root: {path}"})
    if not target.exists():
        return ToolResult(data={"error": f"not found: {path}"})
    if not target.is_dir():
        return ToolResult(data={"error": f"not a directory: {path}"})
    return ToolResult(data={"files": _walk(target, root, _hidden_set(agent))})


@register_dispatch("file_read")
async def _read(agent_id: str = "", path: str = "", **_kw) -> ToolResult:
    agent, err = _get_agent_or_error(agent_id)
    if err:
        return err
    if not path:
        return ToolResult(data={"error": "path required"})
    root = _agent_root(agent)
    try:
        target = _resolve_safe(root, path)
    except ValueError:
        return ToolResult(data={"error": f"path outside root: {path}"})
    if not target.exists():
        return ToolResult(data={"error": f"not found: {path}"})
    if target.is_dir():
        return ToolResult(data={"error": f"is a directory: {path}"})

    ext = target.suffix.lower()
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".ico"}
    if ext in image_exts:
        data = base64.b64encode(target.read_bytes()).decode("ascii")
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")
        return ToolResult(
            data={"path": path, "kind": "image", "image_base64": data, "mime": mime}
        )
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ToolResult(data={"error": f"binary file, cannot read as text: {path}"})
    return ToolResult(data={"path": path, "content": content})


@register_dispatch("file_write")
async def _write(
    agent_id: str = "", path: str = "", content: str = "", **_kw
) -> ToolResult:
    agent, err = _get_agent_or_error(agent_id)
    if err:
        return err
    ro = _readonly_error(agent)
    if ro:
        return ro
    if not path:
        return ToolResult(data={"error": "path required"})
    root = _agent_root(agent)
    try:
        target = _resolve_safe(root, path)
    except ValueError:
        return ToolResult(data={"error": f"path outside root: {path}"})
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ToolResult(data={"path": path, "written": True})


@register_dispatch("file_delete")
async def _delete(agent_id: str = "", path: str = "", **_kw) -> ToolResult:
    agent, err = _get_agent_or_error(agent_id)
    if err:
        return err
    ro = _readonly_error(agent)
    if ro:
        return ro
    if not path:
        return ToolResult(data={"error": "path required"})
    root = _agent_root(agent)
    try:
        target = _resolve_safe(root, path)
    except ValueError:
        return ToolResult(data={"error": f"path outside root: {path}"})
    if not target.exists():
        return ToolResult(data={"error": f"not found: {path}"})
    if target.is_dir():
        return ToolResult(data={"error": f"is a directory (use rmdir): {path}"})
    target.unlink()
    return ToolResult(data={"path": path, "deleted": True})


@register_dispatch("file_rename")
async def _rename(
    agent_id: str = "", old_path: str = "", new_path: str = "", **_kw
) -> ToolResult:
    agent, err = _get_agent_or_error(agent_id)
    if err:
        return err
    ro = _readonly_error(agent)
    if ro:
        return ro
    if not old_path or not new_path:
        return ToolResult(data={"error": "old_path and new_path required"})
    root = _agent_root(agent)
    try:
        old_t = _resolve_safe(root, old_path)
        new_t = _resolve_safe(root, new_path)
    except ValueError:
        return ToolResult(data={"error": "path outside root"})
    if not old_t.exists():
        return ToolResult(data={"error": f"not found: {old_path}"})
    new_t.parent.mkdir(parents=True, exist_ok=True)
    old_t.rename(new_t)
    return ToolResult(data={"old_path": old_path, "new_path": new_path})


@register_dispatch("file_mkdir")
async def _mkdir(agent_id: str = "", path: str = "", **_kw) -> ToolResult:
    agent, err = _get_agent_or_error(agent_id)
    if err:
        return err
    ro = _readonly_error(agent)
    if ro:
        return ro
    if not path:
        return ToolResult(data={"error": "path required"})
    root = _agent_root(agent)
    try:
        target = _resolve_safe(root, path)
    except ValueError:
        return ToolResult(data={"error": f"path outside root: {path}"})
    target.mkdir(parents=True, exist_ok=True)
    return ToolResult(data={"path": path, "created": True})
