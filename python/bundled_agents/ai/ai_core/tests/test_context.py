"""Deterministic, no-LLM tests for the context-budget primitives + the overflow
strategies (the projection logic). Fast; no kernel, no network."""

from __future__ import annotations

from ai_core.context import (
    DEFAULT_CONTEXT_WINDOW,
    ProjectionCtx,
    budget,
    estimate_one,
    estimate_tokens,
    resolve_context_window,
)
from ai_core.strategies import DEFAULT_STRATEGY, get_strategy, strategy_names
from ai_core.strategies.base import STUB_SUMMARY


def _turn(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def _body(n: int, size: int = 200) -> list[dict]:
    return [
        _turn("user" if i % 2 == 0 else "assistant", f"turn{i}-" + "x" * size)
        for i in range(n)
    ]


async def _fake_summary(_msgs) -> str:
    return "SUMMARY"


def _ctx(bud: int, recent_n: int = 4, summarize=_fake_summary) -> ProjectionCtx:
    return ProjectionCtx(
        budget=bud, recent_n=recent_n, summarize=summarize, self_id="ai", kernel=None
    )


# ── primitives ──────────────────────────────────────────────────────


def test_estimate_scale_and_monotonic():
    assert estimate_one(_turn("user", "x" * 400)) >= 100  # ~400/4
    assert estimate_tokens(_body(4)) > estimate_tokens(_body(2))


def test_window_precedence():
    assert resolve_context_window({"context_window": 8000, "num_ctx": 2000}) == 8000
    assert resolve_context_window({"num_ctx": 2000}) == 2000
    assert resolve_context_window({}) == DEFAULT_CONTEXT_WINDOW


def test_budget_floor():
    assert budget({"context_window": 100, "output_reserve": 1000}) == 256


def test_registry():
    assert set(strategy_names()) == {"compact", "truncate", "memgpt"}
    assert DEFAULT_STRATEGY == "compact"
    assert get_strategy("nope") is None  # unknown ⇒ None (caller errors), no default


# ── strategies ──────────────────────────────────────────────────────


async def test_compact_keeps_recent_and_summarizes_overflow():
    body = _body(10)
    out = await get_strategy("compact")(
        body, [_turn("system", "S")], {}, _ctx(bud=1_000_000, recent_n=4)
    )
    assert out[0]["role"] == "user" and "SUMMARY" in out[0]["content"]  # summary leads
    assert out[1:] == body[-4:]  # recent verbatim
    assert body[0] not in out  # oldest only in the summary


async def test_truncate_keeps_first_and_recent_no_summarizer():
    called = []

    async def spy(_msgs):
        called.append(1)
        return "S"

    body = _body(10)
    out = await get_strategy("truncate")(
        body, [], {}, _ctx(bud=1_000_000, recent_n=4, summarize=spy)
    )
    assert out[0] == body[0]  # first (task) turn kept
    assert out[1]["content"].startswith("[…")  # omission marker
    assert out[-4:] == body[-4:]  # recent kept
    assert not called, "truncate must NOT call the summarizer"


async def test_memgpt_warns_then_compacts():
    body = _body(10)
    out = await get_strategy("memgpt")(body, [], {}, _ctx(bud=1_000_000, recent_n=4))
    assert "memory notice" in out[0]["content"]
    assert any("SUMMARY" in m.get("content", "") for m in out)


async def test_tool_pairing_never_orphans_role_tool():
    body = [
        _turn("user", "u0"),
        {"role": "assistant", "content": "a", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "tool_call_id": "1", "content": "r"},
        _turn("assistant", "done"),
        _turn("user", "u-live"),
    ]
    # recent_n=3 would start the recent window on the role:tool (idx 2); must snap back.
    out = await get_strategy("compact")(body, [], {}, _ctx(bud=1_000_000, recent_n=3))
    recent = out[1:]  # after the summary turn
    assert not (recent and recent[0].get("role") == "tool")


async def test_summarizer_failure_degrades_to_stub():
    async def boom(_msgs):
        raise RuntimeError("nope")

    out = await get_strategy("compact")(
        _body(10), [], {}, _ctx(bud=1_000_000, summarize=boom)
    )
    assert STUB_SUMMARY in out[0]["content"]


async def test_tight_budget_keeps_live_user_turn():
    body = _body(10)
    # a tiny body-budget — projection must still keep the LAST (live) turn.
    out = await get_strategy("truncate")(body, [], {}, _ctx(bud=80, recent_n=4))
    assert out[-1] == body[-1]


# ── the _run projection seam (deterministic) ────────────────────────

import types  # noqa: E402

from ai_core.core import _project_context, _projection  # noqa: E402


class _FakeProvider:
    async def chat(self, messages, tools):
        yield "FAKESUMMARY"


def _cfg():
    return types.SimpleNamespace(name="test_backend")


def _msgs(n):
    return [_turn("system", "sys")] + _body(n)


async def test_seam_short_circuits_when_under_budget():
    msgs = [_turn("system", "S"), _turn("user", "hi")]
    out = await _project_context({}, _cfg(), _FakeProvider(), "ai", None, msgs)
    assert out == msgs  # unchanged
    assert _projection["ai"] == {"fired": False}


async def test_seam_fires_and_records_projection():
    msgs = _msgs(20)  # big history
    out = await _project_context(
        {"context_window": 500, "output_reserve": 0, "context_strategy": "compact"},
        _cfg(),
        _FakeProvider(),
        "ai",
        None,
        msgs,
    )
    assert estimate_tokens(out) <= 500  # fits the window now
    assert out[0]["role"] == "system"  # system block preserved
    assert _projection["ai"]["fired"] is True
    assert _projection["ai"]["strategy"] == "compact"
    assert _projection["ai"]["summarized"] is True
    assert _projection["ai"]["dropped_turns"] > 0


async def test_seam_failsafe_when_system_block_too_big():
    big_system = _turn("system", "S" * 8000)  # ~2000 tok, bigger than the window
    msgs = [big_system, _turn("user", "hi")]
    out = await _project_context(
        {"context_window": 1000, "output_reserve": 0},
        _cfg(),
        _FakeProvider(),
        "ai",
        None,
        msgs,
    )
    assert isinstance(out, dict) and "context_insufficient" in out["error"]


async def test_seam_unknown_strategy_errors():
    msgs = _msgs(20)
    out = await _project_context(
        {"context_window": 500, "output_reserve": 0, "context_strategy": "bogus"},
        _cfg(),
        _FakeProvider(),
        "ai",
        None,
        msgs,
    )
    assert isinstance(out, dict) and "bogus" in out["error"]
