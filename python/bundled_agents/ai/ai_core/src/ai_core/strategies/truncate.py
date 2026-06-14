"""`truncate` — keep the first (task-framing) turn + the recent turns, drop the
middle. Cheap: NO summarizer call."""

from __future__ import annotations

from ai_core.context import ProjectionCtx, estimate_one
from ai_core.strategies.base import fit_tail


async def truncate(
    body: list[dict], system_block: list[dict], rec: dict, ctx: ProjectionCtx
) -> list[dict]:
    if len(body) <= 1:
        return fit_tail(body, ctx.budget)
    first = body[0]
    marker = {"role": "user", "content": "[… earlier turns omitted …]"}
    head_cost = estimate_one(first) + estimate_one(marker)
    tail = fit_tail(body[1:], max(0, ctx.budget - head_cost))
    return [first, marker] + tail
