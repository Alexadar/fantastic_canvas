"""Tests for quickstart bundle — @chat_run wizard logic."""


async def test_quickstart_fresh_adds_canvas(setup):
    """On fresh project, quickstart auto-adds canvas."""
    engine, bc, pr = setup
    # Clear all agents, add only quickstart
    for a in engine.store.list_agents():
        engine.store.delete_agent(a["id"])
    engine.store.create_agent(bundle="quickstart")
    # Re-init
    from core.tools import init_tools, _state
    _state._on_agent_created.clear()
    init_tools(engine, bc, pr)

    async def no_ask(prompt): raise AssertionError("ask() should not be called")
    messages = []
    def mock_say(msg): messages.append(msg)

    from bundled_agents.quickstart.tools import run
    await run(no_ask, mock_say)

    assert engine.store.find_by_bundle("canvas") is not None
    assert engine.store.find_by_bundle("quickstart") is None  # self-deleted
    assert any("Quickstart" in m for m in messages)


async def test_quickstart_already_configured(setup):
    """With existing agents, quickstart says 'already configured' and exits."""
    engine, bc, pr = setup  # has canvas + terminal
    engine.store.create_agent(bundle="quickstart")

    messages = []
    def mock_say(msg): messages.append(msg)
    async def no_ask(prompt): raise AssertionError("ask() should not be called")

    from bundled_agents.quickstart.tools import run
    await run(no_ask, mock_say)

    assert any("already configured" in m for m in messages)
    assert engine.store.find_by_bundle("quickstart") is None
