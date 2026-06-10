"""file_bridge bundle — the fs-transport member of the io family.

The disk is OUTSIDE the trust domain: crossing kernel↔disk is an IO edge,
gated exactly like a bridge leg — SEALED BY DEFAULT (absent `ingress_rule`
⇒ every verb except `reflect` denies with the teaching shape). Open it
consciously with `ingress_rule=allow_all`. Even open, the LAW is
running-dir only: the `root` AND every path are clamped inside the dir the
kernel runs in (`../`, `~`, absolute escapes, outward symlinks all refuse).

Each file_bridge owns a `root` directory and a `readonly` flag. Path safety:
every verb resolves `root/path` and refuses if the result escapes `root`.

Verbs:
  reflect            -> {sentence, root, readonly, hidden_count, ingress, egress, sealed, see}
  list   path?       -> {files: [{name, path, type, size?}, ...]}
  read   path        -> {path, content} | {path, image_base64, mime}
  write  path text   -> {path, written: true}            (refused if readonly)
  delete path        -> {path, deleted: true}            (refused if readonly)
  rename old_path new_path -> {old_path, new_path}        (refused if readonly)
  mkdir  path        -> {path, created: true}            (refused if readonly)
"""

from __future__ import annotations

import base64
import mimetypes
import os
from pathlib import Path

from io_bridge import describe as _describe
from io_bridge import gate_inbound, resolve_ingress

DEFAULT_HIDDEN = [".git", ".env", ".fantastic", "node_modules", "__pycache__"]
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _root(rec: dict) -> Path:
    """The bridge's root, CLAMPED to the running dir: relative roots resolve under
    cwd; an absolute root is allowed only if it lies inside cwd. `~`/`..` escapes
    refuse loudly — a file_bridge can never see outside the dir the kernel runs in."""
    r = rec.get("root", "") or ""
    base = Path.cwd().resolve()
    root = (Path(r) if Path(r).is_absolute() else base / r).resolve()
    try:
        root.relative_to(base)
    except ValueError:
        raise ValueError(f"file_bridge: root {r!r} escapes the running dir") from None
    return root


def _hidden(rec: dict) -> list[str]:
    return list(rec.get("hidden", DEFAULT_HIDDEN))


def _is_hidden(name: str, hidden: list[str]) -> bool:
    return name in hidden or any(name == p for p in hidden)


def _resolve_safe(rec: dict, path: str) -> Path:
    root = _root(rec)
    rel = (path or "").lstrip("/")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(f"path {path!r} escapes root") from None
    return target


def _readonly_or_none(rec: dict) -> dict | None:
    if rec.get("readonly"):
        return {"error": "agent is readonly"}
    return None


# ─── verbs ──────────────────────────────────────────────────────


async def _reflect(id, payload, kernel):
    """Identity + filesystem root + readonly flag + auth posture (ingress/egress/sealed/see). No args."""
    rec = kernel.get(id) or {}
    try:
        root_display = str(_root(rec))
        root_error = None
    except ValueError as e:
        # Reflect NEVER raises — show the configured string + the violation.
        root_display = str(rec.get("root", "") or "")
        root_error = str(e)
    out = {
        "id": id,
        "sentence": "Filesystem edge of the io family — sealed by default, running-dir only.",
        "root": root_display,
        "readonly": bool(rec.get("readonly")),
        "hidden_count": len(_hidden(rec)),
        "verbs": {
            n: (f.__doc__ or "").strip().splitlines()[0] for n, f in VERBS.items()
        },
        **_describe(rec),
    }
    if root_error:
        out["root_error"] = root_error
    return out


async def _boot(id, payload, kernel):
    """No-op. Returns None."""
    return None


async def _list(id, payload, kernel):
    """args: path:str (default ''). Returns {path, files:[{name, path, type, size?}, ...]}. Hides DEFAULT_HIDDEN entries (.git, .env, .fantastic, …)."""
    rec = kernel.get(id) or {}
    path = payload.get("path", "")
    try:
        root = _root(rec)
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    if not target.exists():
        return {"error": f"path {path!r} does not exist"}
    if not target.is_dir():
        return {"error": f"path {path!r} is not a directory"}
    hidden = _hidden(rec)
    files = []
    try:
        for entry in sorted(target.iterdir()):
            if _is_hidden(entry.name, hidden):
                continue
            rel = str(entry.relative_to(root))
            if entry.is_dir():
                files.append({"name": entry.name, "path": rel, "type": "dir"})
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = -1
                files.append(
                    {
                        "name": entry.name,
                        "path": rel,
                        "type": "file",
                        "size": size,
                    }
                )
    except PermissionError as e:
        return {"error": str(e)}
    return {"path": path, "files": files}


async def _read(id, payload, kernel):
    """args: path:str (req). Returns {path, content:str} for text, {path, image_base64, mime} for images, {path, bytes:bytes, mime} for any other binary (PDF, fonts, archives, etc.) — raw bytes ride the kernel's binary protocol over WS, zero-copy in-process. Refuses paths outside root."""
    rec = kernel.get(id) or {}
    path = payload.get("path", "")
    try:
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    if not target.exists() or not target.is_file():
        return {"error": f"file {path!r} not found"}
    ext = target.suffix.lower()
    if ext in IMAGE_EXT:
        data = target.read_bytes()
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }.get(ext, "application/octet-stream")
        return {
            "path": path,
            "image_base64": base64.b64encode(data).decode("ascii"),
            "mime": mime,
        }
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # Generic binary: PDF, font, archive, audio, video. Raw bytes —
        # over WS the kernel's binary protocol (`_binary_path`) auto-
        # detects + ships in a binary frame; in-process the webapp's
        # /file/ route reads them and pipes straight to the HTTP
        # response. No base64 round-trip in either path.
        data = target.read_bytes()
        mime, _ = mimetypes.guess_type(target.name)
        return {
            "path": path,
            "bytes": data,
            "mime": mime or "application/octet-stream",
        }
    return {"path": path, "content": content}


async def _write(id, payload, kernel):
    """args: path:str (req), content:str (req). Returns {path, written:true, bytes}. Creates parent dirs. Refused if readonly."""
    rec = kernel.get(id) or {}
    if err := _readonly_or_none(rec):
        return err
    path = payload.get("path", "")
    content = payload.get("content", "")
    try:
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": path, "written": True, "bytes": len(content.encode("utf-8"))}


def _rmtree(target: Path) -> None:
    """Recursive delete of a dir (depth-first). Clamping already done by the
    caller via `_resolve_safe`, so this only ever walks inside `root`."""
    for sub in target.iterdir():
        if sub.is_dir() and not sub.is_symlink():
            _rmtree(sub)
        else:
            sub.unlink()
    target.rmdir()


async def _delete(id, payload, kernel):
    """args: path:str (req), recursive:bool=False. Returns {path, deleted:true}.
    A bare delete removes a file or an EMPTY dir; `recursive:true` removes a dir
    and everything under it (still clamped to root). Refused if readonly."""
    rec = kernel.get(id) or {}
    if err := _readonly_or_none(rec):
        return err
    path = payload.get("path", "")
    try:
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    if not target.exists():
        return {"error": f"path {path!r} does not exist"}
    try:
        if target.is_dir():
            if payload.get("recursive"):
                _rmtree(target)
            else:
                os.rmdir(target)
        else:
            target.unlink()
    except OSError as e:
        return {"error": str(e)}
    return {"path": path, "deleted": True}


async def _rename(id, payload, kernel):
    """args: old_path:str, new_path:str (both req). Returns {old_path, new_path}. Creates new parent dirs. Refused if readonly."""
    rec = kernel.get(id) or {}
    if err := _readonly_or_none(rec):
        return err
    old = payload.get("old_path", "")
    new = payload.get("new_path", "")
    try:
        o = _resolve_safe(rec, old)
        n = _resolve_safe(rec, new)
    except ValueError as e:
        return {"error": str(e)}
    if not o.exists():
        return {"error": f"path {old!r} does not exist"}
    n.parent.mkdir(parents=True, exist_ok=True)
    o.rename(n)
    return {"old_path": old, "new_path": new}


async def _mkdir(id, payload, kernel):
    """args: path:str (req). Returns {path, created:true}. Recursive (parents ok). Refused if readonly."""
    rec = kernel.get(id) or {}
    if err := _readonly_or_none(rec):
        return err
    path = payload.get("path", "")
    try:
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    target.mkdir(parents=True, exist_ok=True)
    return {"path": path, "created": True}


# ─── the stream protocol (SOURCE / SINK) ────────────────────────
# A stateless cursor stream: any consumer (file serving, a pump, kernel_state)
# pulls/pushes bytes by id + verb — weak-coupled, no session handle. file_bridge is
# the fs IMPLEMENTOR of this protocol; a network_bridge implements the same verbs over
# the wire, so a consumer is storage-agnostic (G1: the provider is just an id).


async def _read_stream(id, payload, kernel):
    """args: path:str (req), offset:int=0, length:int=65536. The SOURCE half — returns
    ONE chunk {path, offset, b64, next_offset, eof, size}; pull the next by calling
    again with offset=next_offset until eof. `b64` is the chunk base64-encoded (JSON-
    safe over any transport). Stateless cursor — no open handle, weak-coupled by id."""
    rec = kernel.get(id) or {}
    path = payload.get("path", "")
    offset = int(payload.get("offset", 0) or 0)
    length = int(payload.get("length", 65536) or 65536)
    try:
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    if not target.exists() or not target.is_file():
        return {"error": f"file {path!r} not found"}
    size = target.stat().st_size
    with target.open("rb") as f:
        f.seek(offset)
        chunk = f.read(max(0, length))
    next_offset = offset + len(chunk)
    return {
        "path": path,
        "offset": offset,
        "b64": base64.b64encode(chunk).decode("ascii"),
        "next_offset": next_offset,
        "eof": next_offset >= size,
        "size": size,
    }


async def _write_stream(id, payload, kernel):
    """args: path:str (req), b64:str (req — one chunk, base64; or `content`:str for
    text), offset:int? (default = append at end), truncate:bool=False. The SINK half —
    a producer pushes chunks by calling repeatedly. Pass truncate:true on the first
    chunk to start fresh. Returns {path, written, offset, size}. Refused if readonly."""
    rec = kernel.get(id) or {}
    if err := _readonly_or_none(rec):
        return err
    path = payload.get("path", "")
    if "b64" in payload:
        data = base64.b64decode(payload["b64"])
    elif "content" in payload:
        data = str(payload["content"]).encode("utf-8")
    else:
        data = payload.get("bytes", b"")
        if isinstance(data, str):
            data = data.encode("utf-8")
    try:
        target = _resolve_safe(rec, path)
    except ValueError as e:
        return {"error": str(e)}
    target.parent.mkdir(parents=True, exist_ok=True)
    if payload.get("truncate") or not target.exists():
        target.write_bytes(b"")
    offset = payload.get("offset")
    offset = target.stat().st_size if offset is None else int(offset)
    with target.open("r+b") as f:
        f.seek(offset)
        f.write(data)
    return {
        "path": path,
        "written": len(data),
        "offset": offset,
        "size": target.stat().st_size,
    }


# ─── dispatch ───────────────────────────────────────────────────


VERBS = {
    "reflect": _reflect,
    "boot": _boot,
    "list": _list,
    "read": _read,
    "write": _write,
    "read_stream": _read_stream,
    "write_stream": _write_stream,
    "delete": _delete,
    "rename": _rename,
    "mkdir": _mkdir,
}

UNGATED = {"reflect"}  # discovery must work on a sealed bridge


async def handler(id: str, payload: dict, kernel) -> dict | None:
    t = payload.get("type")
    fn = VERBS.get(t)
    if fn is None:
        return {"error": f"file_bridge: unknown type {t!r}"}
    if t not in UNGATED:
        # AUTH GATE — the fs edge, gated like any io_bridge leg (sealed by default).
        decision = gate_inbound(
            resolve_ingress(kernel.get(id) or {}),
            "call",
            {"target": id, "payload": payload},
        )
        if not decision.allowed:
            out = {"error": decision.reason, "reason": "unauthorized"}
            if decision.hint:
                out["hint"] = decision.hint
            if decision.see:
                out["see"] = decision.see
            return out
    return await fn(id, payload, kernel)
