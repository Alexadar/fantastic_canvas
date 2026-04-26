"""canvas bundle — spatial UI host as an agent.

The canvas is a web page that renders OTHER agents as positioned iframes.
Layout is stored on each agent's record: x, y, width, height. Drag/resize
in the browser sends update_agent through core; everyone watching `core`
(including this canvas) gets `agent_updated` events.

Verbs:
  reflect     -> {sentence, agent_count, viewport_default}
  discover    args: x, y, w, h  -> {agents: [...]} agents intersecting the rect
  boot        -> nothing (canvas is purely browser-driven)
"""

from __future__ import annotations


def _rect(rec: dict) -> tuple[float, float, float, float]:
    return (
        float(rec.get("x", 0)),
        float(rec.get("y", 0)),
        float(rec.get("width", 320)),
        float(rec.get("height", 220)),
    )


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw < bx or bx + bw < ax or ay + ah < by or by + bh < ay)


# ─── verbs ──────────────────────────────────────────────────────


async def _reflect(id, payload, kernel):
    """Identity + viewport defaults + total agent count. No args."""
    rec = kernel.get(id) or {}
    return {
        "id": id,
        "sentence": "Spatial canvas. Renders other agents as positioned iframes; drag/resize updates their record.",
        "viewport_default": {
            "width": int(rec.get("width", 1600)),
            "height": int(rec.get("height", 900)),
        },
        "agent_count": len(kernel.list()),
        "verbs": {n: (f.__doc__ or "").strip().splitlines()[0] for n, f in VERBS.items()},
    }


async def _boot(id, payload, kernel):
    """No-op. Returns None."""
    return None


async def _discover(id, payload, kernel):
    """args: x:float, y:float, w:float (>0), h:float (>0). Returns {agents:[{id,x,y,width,height},...]} for agents whose rect intersects."""
    x = float(payload.get("x", 0))
    y = float(payload.get("y", 0))
    w = float(payload.get("w", 0))
    h = float(payload.get("h", 0))
    if w <= 0 or h <= 0:
        return {"error": "discover: w and h required and > 0"}
    target_rect = (x, y, w, h)
    hits = []
    for a in kernel.list():
        if a["id"] == id:
            continue
        if _intersects(_rect(a), target_rect):
            hits.append({
                "id": a["id"],
                "x": a.get("x", 0), "y": a.get("y", 0),
                "width": a.get("width", 320), "height": a.get("height", 220),
            })
    return {"agents": hits}


# ─── dispatch ───────────────────────────────────────────────────


VERBS = {
    "reflect": _reflect,
    "boot": _boot,
    "discover": _discover,
}


async def handler(id: str, payload: dict, kernel) -> dict | None:
    t = payload.get("type")
    fn = VERBS.get(t)
    if fn is None:
        return {"error": f"canvas: unknown type {t!r}"}
    return await fn(id, payload, kernel)
