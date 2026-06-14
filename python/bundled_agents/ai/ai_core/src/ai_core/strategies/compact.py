"""`compact` — the DEFAULT strategy. Keep the recent turns verbatim + an LLM summary
of the overflow, re-injected as ONE leading turn (the coding-agent hybrid)."""

from __future__ import annotations

from ai_core.context import ProjectionCtx, estimate_one
from ai_core.strategies.base import fit_tail, recent_split, safe_summary


async def compact(
    body: list[dict], system_block: list[dict], rec: dict, ctx: ProjectionCtx
) -> list[dict]:
    overflow, recent = recent_split(body, ctx.recent_n)
    if not overflow:
        return fit_tail(body, ctx.budget)
    summary = await safe_summary(ctx, overflow)
    summary_turn = {
        "role": "user",
        "content": "[Earlier conversation summary]\n" + summary,
    }
    avail = max(0, ctx.budget - estimate_one(summary_turn))
    return [summary_turn] + fit_tail(recent, avail)
