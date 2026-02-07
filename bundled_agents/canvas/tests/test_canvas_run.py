"""Tests for canvas bundle — @chat_run open-in-browser logic."""

import unittest.mock


async def test_canvas_run_adds_and_opens(setup):
    """run canvas adds canvas and opens browser."""
    engine, bc, pr = setup
    # Remove canvas agents to start fresh
    for a in engine.store.list_agents():
        if a.get("bundle") == "canvas":
            for c in engine.store.list_children(a["id"]):
                engine.store.delete_agent(c["id"])
            engine.store.delete_agent(a["id"])
    from core.tools import init_tools, _state
    _state._on_agent_created.clear()
    init_tools(engine, bc, pr)

    responses = iter(["test"])
    async def mock_ask(prompt): return next(responses)
    messages = []
    def mock_say(msg): messages.append(msg)

    from bundled_agents.canvas.tools import run
    with unittest.mock.patch("webbrowser.open") as mock_open:
        await run(mock_ask, mock_say)
        mock_open.assert_called_once()
        assert "canvas/test" in mock_open.call_args[0][0]

    assert engine.store.find_by_bundle("canvas") is not None


async def test_canvas_run_existing_opens(setup):
    """With existing canvas, run opens browser without error."""
    engine, bc, pr = setup  # has canvas "main" + terminal
    messages = []
    def mock_say(msg): messages.append(msg)
    async def mock_ask(prompt): return "main"

    from bundled_agents.canvas.tools import run
    with unittest.mock.patch("webbrowser.open") as mock_open:
        await run(mock_ask, mock_say)
        mock_open.assert_called_once()

    assert any("localhost" in m for m in messages)
    assert engine.store.find_by_bundle("canvas") is not None
