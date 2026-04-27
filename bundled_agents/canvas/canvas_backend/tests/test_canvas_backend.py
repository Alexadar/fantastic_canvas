"""canvas_backend — spatial discovery."""

from __future__ import annotations

from canvas_backend.tools import _intersects, _rect


async def _make_canvas_backend(kernel):
    rec = await kernel.send(
        "core",
        {"type": "create_agent", "handler_module": "canvas_backend.tools"},
    )
    return rec["id"]


def test_intersects_overlapping():
    assert _intersects((0, 0, 10, 10), (5, 5, 10, 10))


def test_intersects_disjoint():
    assert not _intersects((0, 0, 10, 10), (100, 100, 10, 10))


def test_intersects_edge_touch_disjoint():
    """Boxes touching only at the edge should NOT intersect (strict)."""
    assert not _intersects((0, 0, 10, 10), (11, 0, 10, 10))


def test_rect_uses_defaults():
    assert _rect({}) == (0.0, 0.0, 320.0, 220.0)


def test_rect_uses_record_values():
    assert _rect({"x": 5, "y": 6, "width": 100, "height": 200}) == (
        5.0,
        6.0,
        100.0,
        200.0,
    )


async def test_reflect(seeded_kernel):
    cid = await _make_canvas_backend(seeded_kernel)
    r = await seeded_kernel.send(cid, {"type": "reflect"})
    assert r["sentence"].startswith("Spatial canvas")
    assert "discover" in r["verbs"]


async def test_discover_requires_positive_w_h(seeded_kernel):
    cid = await _make_canvas_backend(seeded_kernel)
    r = await seeded_kernel.send(
        cid, {"type": "discover", "x": 0, "y": 0, "w": 0, "h": 0}
    )
    assert "error" in r


async def test_discover_returns_intersecting_agents(seeded_kernel):
    cid = await _make_canvas_backend(seeded_kernel)
    # create an agent at coords
    a = await seeded_kernel.send(
        "core",
        {
            "type": "create_agent",
            "handler_module": "file.tools",
            "x": 100,
            "y": 100,
            "width": 50,
            "height": 50,
        },
    )
    # Discover query overlapping the agent
    r = await seeded_kernel.send(
        cid, {"type": "discover", "x": 0, "y": 0, "w": 200, "h": 200}
    )
    ids = {x["id"] for x in r["agents"]}
    assert a["id"] in ids


async def test_discover_excludes_self(seeded_kernel):
    cid = await _make_canvas_backend(seeded_kernel)
    r = await seeded_kernel.send(
        cid, {"type": "discover", "x": 0, "y": 0, "w": 10000, "h": 10000}
    )
    ids = {x["id"] for x in r["agents"]}
    assert cid not in ids


async def test_unknown_verb_errors(seeded_kernel):
    cid = await _make_canvas_backend(seeded_kernel)
    r = await seeded_kernel.send(cid, {"type": "garbage"})
    assert "error" in r
