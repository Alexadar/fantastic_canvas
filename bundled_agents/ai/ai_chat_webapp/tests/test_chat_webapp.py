"""ai_chat_webapp — provider-agnostic chat UI agent."""

from __future__ import annotations


async def _make(kernel, upstream_id="some_backend"):
    rec = await kernel.send(
        "core",
        {
            "type": "create_agent",
            "handler_module": "ai_chat_webapp.tools",
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
    """Drift guard: served HTML must carry the send/stop button toggle
    that calls the upstream's `interrupt` verb to cancel mid-stream
    (Claude-Code-style cancel). Plus the queued/client_id wiring."""
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "render_html"})
    html = r["html"]
    assert "interrupt" in html, (
        "must call upstream's interrupt verb to cancel mid-stream"
    )
    assert "type: 'interrupt'" in html or "'interrupt'" in html, (
        "the interrupt call must reach upstream"
    )
    # Per-client wiring (client_id from localStorage; queued event handling).
    assert "clientId" in html
    assert "ai_chat_client_id:" in html
    assert "queued" in html, "must mark message as queued when lock contended"


async def test_render_html_has_status_pipeline_and_fifo(seeded_kernel):
    """Drift guard: the served HTML must carry the status-stream
    pipeline (status verb on boot, status event subscription, phase
    pill, tool blocks, FIFO state) and the legacy singleton must be
    gone."""
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "render_html"})
    html = r["html"]
    # Status verb call on boot.
    assert "type: 'status'" in html, "boot must call upstream's status verb"
    # Status event subscription.
    assert "t.on('status'" in html, "must subscribe to status events"
    # Tool block markup.
    assert 'class="tool-block' in html or "tool-block" in html
    assert "data-call-id" in html or "callId" in html
    # Status footer with phase pill.
    assert 'id="status-footer"' in html
    assert "phase-pill" in html
    # FIFO state (replaces singleton pendingUserBubble).
    assert "queuedBubbles" in html, "must keep a Map of queued bubbles"
    # Boot snapshot is consumed.
    assert "mine_pending" in html
    assert "others_pending" in html
    # CSS pulse animation present.
    assert "@keyframes" in html or "keyframes pulse" in html
    # Negative drift guard: legacy singleton is gone.
    assert "pendingUserBubble" not in html, (
        "pendingUserBubble singleton must be replaced by FIFO Map"
    )
