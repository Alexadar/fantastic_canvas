"""cli singleton — terminal renderer.

Receives `token`, `done`, `say`, `error` payloads. Prints to stdout.
Unknown verbs are silently dropped (cli is a render sink).
"""

from __future__ import annotations

import sys


# ─── verbs ──────────────────────────────────────────────────────


async def _reflect(id, payload, kernel):
    """Identity + accepted event types. No args."""
    return {
        "id": id,
        "sentence": "Terminal renderer. Prints incoming events to stdout.",
        "verbs": {n: (f.__doc__ or "").strip().splitlines()[0] for n, f in VERBS.items()},
        "accepts": ["token", "done", "say", "error"],
    }


async def _token(id, payload, kernel):
    """args: text:str. Writes to stdout (no newline). Returns None."""
    sys.stdout.write(payload.get("text", ""))
    sys.stdout.flush()
    return None


async def _done(id, payload, kernel):
    """args: none. Emits a single newline; closes a token-stream cleanly. Returns None."""
    print()
    return None


async def _say(id, payload, kernel):
    """args: text:str, source:str?. Prints `  [source] text` on its own line. Returns None."""
    text = payload.get("text", "")
    src = payload.get("source", "")
    prefix = f"  [{src}] " if src else "  "
    print(f"{prefix}{text}")
    return None


async def _error(id, payload, kernel):
    """args: text:str. Prints `  ERROR: text` on its own line. Returns None."""
    print(f"  ERROR: {payload.get('text', '')}")
    return None


# ─── dispatch ───────────────────────────────────────────────────


VERBS = {
    "reflect": _reflect,
    "token": _token,
    "done": _done,
    "say": _say,
    "error": _error,
}


async def handler(id: str, payload: dict, kernel) -> dict | None:
    fn = VERBS.get(payload.get("type"))
    if fn is None:
        return None  # cli is silent on unknown verbs
    return await fn(id, payload, kernel)
