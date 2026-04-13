"""Tests for quickstart bundle — @chat_run wizard logic."""


async def test_quickstart_fresh_adds_web_and_canvas(setup):
    """On fresh project, quickstart creates web_main + canvas_main (canvas parent=web_main)."""
    engine, bc, pr = setup
    # Clear all agents, add only quickstart
    for a in engine.store.list_agents():
        engine.store.delete_agent(a["id"])
    engine.store.create_agent(bundle="quickstart")
    # Re-init
    from core.tools import init_tools, _state

    _state._on_agent_created.clear()
    init_tools(engine, bc, pr)

    async def no_ask(prompt):
        raise AssertionError("ask() should not be called")

    messages = []

    def mock_say(msg):
        messages.append(msg)

    from bundled_agents.quickstart.tools import run

    await run(no_ask, mock_say)

    web = engine.store.get_agent("web_main")
    canvas = engine.store.get_agent("canvas_main")
    assert web is not None
    assert web["bundle"] == "web"
    assert web.get("is_container") is True
    assert canvas is not None
    assert canvas["bundle"] == "canvas"
    assert canvas.get("parent") == "web_main"
    assert canvas.get("is_container") is True
    assert engine.store.find_by_bundle("quickstart") is None  # self-deleted
    assert any("Quickstart" in m for m in messages)


async def test_quickstart_new_agents_parent_to_canvas(setup):
    """After quickstart, a fresh agent auto-parents to canvas_main (not web_main)."""
    engine, bc, pr = setup
    for a in engine.store.list_agents():
        engine.store.delete_agent(a["id"])
    engine.store.create_agent(bundle="quickstart")

    from core.tools import init_tools, _state

    _state._on_agent_created.clear()
    init_tools(engine, bc, pr)

    from bundled_agents.quickstart.tools import run

    await run(lambda *_: None, lambda *_: None)

    # Now simulate creating a terminal — canvas auto-parent hook should place
    # it under canvas_main, not web_main.
    term = engine.store.create_agent(bundle="terminal")
    for hook in _state._on_agent_created:
        hook(term["id"], term)
    refreshed = engine.store.get_agent(term["id"])
    assert refreshed.get("parent") == "canvas_main"


async def test_quickstart_already_configured(setup):
    """With existing agents, quickstart says 'already configured' and exits."""
    engine, bc, pr = setup  # has canvas + terminal
    engine.store.create_agent(bundle="quickstart")

    messages = []

    def mock_say(msg):
        messages.append(msg)

    async def no_ask(prompt):
        raise AssertionError("ask() should not be called")

    from bundled_agents.quickstart.tools import run

    await run(no_ask, mock_say)

    assert any("already configured" in m for m in messages)
    assert engine.store.find_by_bundle("quickstart") is None
