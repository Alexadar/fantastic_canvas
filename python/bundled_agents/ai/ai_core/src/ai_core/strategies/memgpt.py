"""`memgpt` — inject a memory-pressure WARNING (inviting the model to persist salient
facts to its memory agent), then compact. The persist is the model's emergent NEXT-turn
decision (the warning lands the turn after overflow) — matching the emergent-memory
north-star validated by `test_ai_memory_discovery.py`."""

from __future__ import annotations

from ai_core.context import ProjectionCtx, estimate_one
from ai_core.strategies.compact import compact

WARNING_TURN = {
    "role": "user",
    "content": (
        "[memory notice] Your conversation is being compacted to fit the context "
        "window. If there are durable facts worth keeping (names, decisions, "
        "preferences), save them to your memory agent now via the send tool — the "
        "earlier turns are being summarized."
    ),
}


async def memgpt(
    body: list[dict], system_block: list[dict], rec: dict, ctx: ProjectionCtx
) -> list[dict]:
    inner = ProjectionCtx(
        budget=max(0, ctx.budget - estimate_one(WARNING_TURN)),
        recent_n=ctx.recent_n,
        summarize=ctx.summarize,
        self_id=ctx.self_id,
        kernel=ctx.kernel,
    )
    compacted = await compact(body, system_block, rec, inner)
    return [WARNING_TURN] + compacted
