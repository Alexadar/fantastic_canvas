"""canvas_webapp — spatial UI agent fronting a canvas_backend.

Holds an `upstream_id` pointing at the canvas backend whose `discover`
verb scopes which agents the UI surfaces. Real work in `webapp/index.html`.

Also owns the per-canvas particle background animation (bganim). The
default body ships at `webapp/default_bganim.js`; per-canvas overrides
are written through a file agent (`file_agent_id`) at
`.fantastic/agents/<self_id>/bganim.js`. The browser fetches the
source via `get_bganim`, recompiles on `bganim_updated` events.
"""

from __future__ import annotations

from importlib import resources


def _bundled_html() -> str:
    """Read the bundle's index.html from package resources, NOT cached."""
    return (resources.files("canvas_webapp") / "webapp" / "index.html").read_text(
        "utf-8"
    )


def _default_bganim_source() -> str:
    return (
        resources.files("canvas_webapp") / "webapp" / "default_bganim.js"
    ).read_text("utf-8")


def _bganim_guide() -> str:
    return (resources.files("canvas_webapp") / "webapp" / "bganim.md").read_text(
        "utf-8"
    )


def _override_path(self_id: str) -> str:
    return f".fantastic/agents/{self_id}/bganim.js"


async def _read_override(self_id: str, kernel) -> str | None:
    fid = (kernel.get(self_id) or {}).get("file_agent_id")
    if not fid:
        return None
    r = await kernel.send(fid, {"type": "read", "path": _override_path(self_id)})
    if r and "content" in r:
        return r["content"]
    return None


# ─── verbs ──────────────────────────────────────────────────────


async def _reflect(id, payload, kernel):
    """Identity + upstream + bganim origin + file_agent_id binding. No args."""
    rec = kernel.get(id) or {}
    override = await _read_override(id, kernel)
    return {
        "id": id,
        "sentence": "Spatial canvas UI fronting an upstream canvas backend.",
        "upstream_id": rec.get("upstream_id"),
        "file_agent_id": rec.get("file_agent_id"),
        "bganim_origin": "file" if override is not None else "default",
        "verbs": {
            n: (f.__doc__ or "").strip().splitlines()[0] for n, f in VERBS.items()
        },
        "emits": {
            "bganim_updated": "{type:'bganim_updated'} — broadcast on the canvas's own inbox after set_bganim writes new source",
        },
    }


async def _get_webapp(id, payload, kernel):
    """No args. Returns canvas UI descriptor: {url, default_width, default_height, title}."""
    return {
        "url": f"/{id}/",
        "default_width": 800,
        "default_height": 600,
        "title": "canvas",
    }


async def _get_bganim(id, payload, kernel):
    """No args. Returns {source:str, origin:'file'|'default'} — the per-particle JS body the canvas runs."""
    override = await _read_override(id, kernel)
    if override is not None:
        return {"source": override, "origin": "file"}
    return {"source": _default_bganim_source(), "origin": "default"}


async def _set_bganim(id, payload, kernel):
    """args: source:str (req, non-empty). Writes via file_agent_id; emits bganim_updated; UI hot-reloads. Returns {ok:true, bytes}. Failfast if file_agent_id unset."""
    rec = kernel.get(id) or {}
    fid = rec.get("file_agent_id")
    if not fid:
        return {"error": "canvas_webapp: file_agent_id required"}
    body = payload.get("source", "")
    if not isinstance(body, str) or not body.strip():
        return {"error": "canvas_webapp: source must be a non-empty string"}
    r = await kernel.send(
        fid,
        {
            "type": "write",
            "path": _override_path(id),
            "content": body,
        },
    )
    if r and r.get("error"):
        return {"error": f"canvas_webapp: file write failed: {r['error']}"}
    await kernel.emit(id, {"type": "bganim_updated"})
    return {"ok": True, "bytes": len(body.encode("utf-8"))}


async def _get_bganim_guide(id, payload, kernel):
    """No args. Returns {guide:str} — the bganim.md prompt spec for LLM-generated bodies."""
    return {"guide": _bganim_guide()}


async def _render_html(id, payload, kernel):
    """No args. Returns {html:str} — bundled webapp/index.html, read fresh on each call."""
    return {"html": _bundled_html()}


async def _boot(id, payload, kernel):
    """No-op. Returns None."""
    return None


# ─── dispatch ───────────────────────────────────────────────────


VERBS = {
    "reflect": _reflect,
    "get_webapp": _get_webapp,
    "get_bganim": _get_bganim,
    "set_bganim": _set_bganim,
    "get_bganim_guide": _get_bganim_guide,
    "render_html": _render_html,
    "boot": _boot,
}


async def handler(id: str, payload: dict, kernel) -> dict | None:
    t = payload.get("type")
    fn = VERBS.get(t)
    if fn is None:
        return {"error": f"canvas_webapp: unknown type {t!r}"}
    return await fn(id, payload, kernel)
