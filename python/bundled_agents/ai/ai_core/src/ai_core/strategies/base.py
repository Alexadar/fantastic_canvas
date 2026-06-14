"""Shared helpers + the STRATEGY contract for ai_core context-overflow strategies.

A strategy is an async projection: given the conversation BODY (history + the live user
turn, WITHOUT the system block), return a shorter body that fits `ctx.budget`. The
system block is re-prepended by the caller (`core._run`). The durable chat store is
NEVER touched — strategies shape only what the model sees this turn.

Tool-pairing is the load-bearing invariant: the OpenAI/NIM wire rejects a `role:tool`
that isn't preceded by its `assistant.tool_calls` turn. Every cut here drops orphaned
leading `role:tool` messages so the projected body is always wire-valid.
"""

from __future__ import annotations

from typing import Awaitable, Callable

from ai_core.context import ProjectionCtx, estimate_one

# (body, system_block, rec, ctx) -> projected body (excludes the system block)
STRATEGY = Callable[
    [list[dict], list[dict], dict, ProjectionCtx], Awaitable[list[dict]]
]

STUB_SUMMARY = "[Earlier conversation omitted — summary unavailable]"


def drop_orphan_tools(turns: list[dict]) -> list[dict]:
    """Drop leading `role:tool` messages whose owning `assistant.tool_calls` turn is
    not present — the model wire would reject them."""
    i = 0
    while i < len(turns) and turns[i].get("role") == "tool":
        i += 1
    return turns[i:]


def fit_tail(turns: list[dict], budget: int) -> list[dict]:
    """Keep the largest SUFFIX of `turns` that fits `budget`, always including the last
    turn (the live request), then drop any orphaned leading tool replies."""
    if not turns:
        return []
    kept = [turns[-1]]
    used = estimate_one(turns[-1])
    for t in reversed(turns[:-1]):
        c = estimate_one(t)
        if used + c > budget:
            break
        kept.insert(0, t)
        used += c
    return drop_orphan_tools(kept)


def recent_split(body: list[dict], recent_n: int) -> tuple[list[dict], list[dict]]:
    """Split `body` into (overflow, recent) at the last `recent_n` turns, snapping the
    boundary back so `recent` never STARTS on an orphaned `role:tool`."""
    start = max(0, len(body) - recent_n)
    while start > 0 and body[start].get("role") == "tool":
        start -= 1
    return body[:start], body[start:]


async def safe_summary(ctx: ProjectionCtx, overflow: list[dict]) -> str:
    """Summarize the overflow via the backend provider; degrade to a stub on ANY
    failure (a degraded artifact — the full transcript is whole in the chat store)."""
    if ctx.summarize is None:
        return STUB_SUMMARY
    try:
        s = await ctx.summarize(overflow)
    except Exception:
        return STUB_SUMMARY
    return (s or "").strip() or STUB_SUMMARY
