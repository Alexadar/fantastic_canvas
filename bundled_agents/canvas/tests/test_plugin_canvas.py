"""Tests for canvas bundle plugin wrappers (tool-level functions)."""

import pytest

from core.tools import _TOOL_DISPATCH
from core.tools._agents import _create_agent


# ── move_agent ────────────────────────────────────────────────────────


async def test_move_agent_success(setup):
    engine, bc, _ = setup
    await _create_agent(agent_id="mv1")
    bc.clear()

    result = await _TOOL_DISPATCH["move_agent"](agent_id="mv1", x=100, y=200)
    assert isinstance(result, dict)
    assert result["x"] == 100
    assert result["y"] == 200
    assert bc.of_type("agent_moved")


async def test_move_agent_not_found(setup):
    result = await _TOOL_DISPATCH["move_agent"](agent_id="nope", x=0, y=0)
    assert "error" in result


# ── resize_agent ──────────────────────────────────────────────────────


async def test_resize_agent_success(setup):
    engine, bc, _ = setup
    await _create_agent(agent_id="rs1")
    bc.clear()

    result = await _TOOL_DISPATCH["resize_agent"](agent_id="rs1", width=500, height=400)
    assert isinstance(result, dict)
    assert result["width"] == 500
    assert result["height"] == 400
    assert bc.of_type("agent_resized")


# ── rename_agent ──────────────────────────────────────────────────────


async def test_rename_agent_success(setup):
    engine, bc, _ = setup
    await _create_agent(agent_id="rn1")
    bc.clear()

    result = await _TOOL_DISPATCH["rename_agent"](agent_id="rn1", display_name="Hello")
    assert isinstance(result, dict)
    assert result["display_name"] == "Hello"
    assert bc.of_type("agent_updated")


# ── update_agent ──────────────────────────────────────────────────────


async def test_update_agent_success(setup):
    engine, bc, _ = setup
    await _create_agent(agent_id="up1")
    bc.clear()

    result = await _TOOL_DISPATCH["update_agent"](agent_id="up1", options={"display_name": "X"})
    assert isinstance(result, dict)
    assert result["display_name"] == "X"
    assert bc.of_type("agent_updated")


async def test_update_agent_error(setup):
    engine, bc, _ = setup
    bc.clear()

    result = await _TOOL_DISPATCH["update_agent"](agent_id="nonexistent", options={"display_name": "X"})
    assert "error" in result
    # no broadcast on error
    assert not bc.of_type("agent_updated")


# ── post_output ───────────────────────────────────────────────────────


async def test_post_output_success(setup):
    await _create_agent(agent_id="po1")
    result = await _TOOL_DISPATCH["post_output"](agent_id="po1", html="<p>hi</p>")
    assert isinstance(result, str)
    assert "Output posted" in result


async def test_post_output_not_found(setup):
    result = await _TOOL_DISPATCH["post_output"](agent_id="nope", html="<p>x</p>")
    assert isinstance(result, str)
    assert "[ERROR]" in result


# ── refresh_agent ─────────────────────────────────────────────────────


async def test_refresh_agent_success(setup):
    engine, bc, _ = setup
    await _create_agent(agent_id="rf1")
    bc.clear()

    result = await _TOOL_DISPATCH["refresh_agent"](agent_id="rf1")
    assert isinstance(result, str)
    assert "refreshed" in result
    assert bc.of_type("agent_refresh")


async def test_refresh_agent_not_found(setup):
    result = await _TOOL_DISPATCH["refresh_agent"](agent_id="nope")
    assert isinstance(result, str)
    assert "[ERROR]" in result


# ── scene_vfx ────────────────────────────────────────────────────────────


async def test_scene_vfx_success(setup):
    engine, bc, _ = setup
    bc.clear()

    result = await _TOOL_DISPATCH["scene_vfx"](js_code="console.log('hello')")
    assert isinstance(result, str)
    assert "VFX" in result or "updated" in result.lower()
    assert bc.of_type("scene_vfx_updated")


# ── scene_vfx_data ───────────────────────────────────────────────────────


async def test_scene_vfx_data_success(setup):
    engine, bc, _ = setup
    bc.clear()

    result = await _TOOL_DISPATCH["scene_vfx_data"](data={"bass": 0.9})
    assert result == "ok"
    msgs = bc.of_type("scene_vfx_data")
    assert len(msgs) == 1
    assert msgs[0]["data"] == {"bass": 0.9}


# ── spatial_discovery ─────────────────────────────────────────────────


async def test_spatial_discovery_closest(setup):
    """spatial_discovery without radius returns closest agent."""
    await _create_agent(agent_id="sd1")
    await _create_agent(agent_id="sd2", options={"x": 100, "y": 0})
    await _create_agent(agent_id="sd3", options={"x": 2000, "y": 2000})

    result = await _TOOL_DISPATCH["spatial_discovery"](agent_id="sd1")
    assert isinstance(result, list)
    # sd2 is closest (but overlaps since default width=800, so distance=0)
    assert len(result) == 1


async def test_spatial_discovery_with_radius(setup):
    """spatial_discovery with radius returns all within range."""
    await _create_agent(agent_id="sr1", options={"x": 0, "y": 0, "width": 100, "height": 100})
    await _create_agent(agent_id="sr2", options={"x": 200, "y": 0, "width": 100, "height": 100})
    await _create_agent(agent_id="sr3", options={"x": 5000, "y": 5000, "width": 100, "height": 100})

    result = await _TOOL_DISPATCH["spatial_discovery"](agent_id="sr1", radius=500)
    assert isinstance(result, list)
    ids = {r["agent_id"] for r in result}
    assert "sr2" in ids
    assert "sr3" not in ids


async def test_spatial_discovery_not_found(setup):
    result = await _TOOL_DISPATCH["spatial_discovery"](agent_id="nonexistent")
    assert result == []
