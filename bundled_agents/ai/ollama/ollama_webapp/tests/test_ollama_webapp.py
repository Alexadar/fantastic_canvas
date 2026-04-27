"""ollama_webapp — chat UI agent."""

from __future__ import annotations


async def _make(kernel, upstream_id="some_backend"):
    rec = await kernel.send(
        "core",
        {
            "type": "create_agent",
            "handler_module": "ollama_webapp.tools",
            "upstream_id": upstream_id,
        },
    )
    return rec["id"]


async def test_reflect_returns_upstream_id(seeded_kernel):
    aid = await _make(seeded_kernel, upstream_id="ollama_backend_x")
    r = await seeded_kernel.send(aid, {"type": "reflect"})
    assert r["upstream_id"] == "ollama_backend_x"
    assert "get_webapp" in r["verbs"]


async def test_get_webapp_returns_descriptor(seeded_kernel):
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "get_webapp"})
    assert r["url"] == f"/{aid}/"
    assert r["default_width"] == 360
    assert r["default_height"] == 480
    assert r["title"] == "chat"


async def test_unknown_verb_errors(seeded_kernel):
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "garbage"})
    assert "error" in r


async def test_render_html_has_stop_button_and_interrupt_wiring(seeded_kernel):
    """Drift guard: served HTML must carry a stop-button state machine
    that calls the upstream's `interrupt` verb to cancel mid-stream
    (Claude-Code-style cancel). Plus the queued/client_id wiring."""
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "render_html"})
    html = r["html"]
    # Stop-button state machine present.
    assert "setBusy" in html, (
        "must have a busy/idle state machine for the send/stop button"
    )
    assert "interrupt" in html, (
        "must call upstream's interrupt verb to cancel mid-stream"
    )
    assert "type: 'interrupt'" in html or "'interrupt'" in html, (
        "the interrupt call must reach upstream"
    )
    # Per-client wiring (client_id from localStorage; queued event handling).
    assert "clientId" in html
    assert "ollama_client_id:" in html
    assert "queued" in html, "must mark message as queued when lock contended"
