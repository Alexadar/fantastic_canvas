"""canvas_webapp — spatial UI agent."""

from __future__ import annotations


async def _make(kernel, upstream_id="some_backend"):
    rec = await kernel.send(
        "core",
        {
            "type": "create_agent",
            "handler_module": "canvas_webapp.tools",
            "upstream_id": upstream_id,
        },
    )
    return rec["id"]


async def test_reflect_returns_upstream_id(seeded_kernel):
    aid = await _make(seeded_kernel, upstream_id="canvas_backend_x")
    r = await seeded_kernel.send(aid, {"type": "reflect"})
    assert r["upstream_id"] == "canvas_backend_x"
    assert "get_webapp" in r["verbs"]


async def test_get_webapp_returns_descriptor(seeded_kernel):
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "get_webapp"})
    assert r["url"] == f"/{aid}/"
    assert r["default_width"] == 800
    assert r["default_height"] == 600
    assert r["title"] == "canvas"


async def test_unknown_verb_errors(seeded_kernel):
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "garbage"})
    assert "error" in r


async def test_render_html_uses_list_members_not_list_agents(seeded_kernel):
    """Drift guard: the served HTML must read membership from the
    upstream canvas_backend's list_members verb, NOT auto-discover via
    core.list_agents. Two canvases would otherwise auto-include the
    same set of webapps."""
    aid = await _make(seeded_kernel)
    r = await seeded_kernel.send(aid, {"type": "render_html"})
    html = r["html"]
    assert "list_members" in html, "refresh() must call upstream.list_members"
    assert "members_updated" in html, (
        "must subscribe to upstream's members_updated event"
    )
    assert "add_agent" in html, "dblclick must auto-add the new pair to this canvas"
    # Auto-discover removed: list_agents stays for record lookup but not
    # as the membership source.
    assert "myBundle" not in html, (
        "same-bundle exclusion was an auto-discover artefact; should be gone"
    )
