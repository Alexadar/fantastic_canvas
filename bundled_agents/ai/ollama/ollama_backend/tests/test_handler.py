"""ollama_backend handler — verb dispatching, file_agent_id failfast, multi-step _run."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch


import ollama_backend.tools as ot


async def _async_iter(items):
    for it in items:
        yield it


class _FakeProvider:
    """Provider stub that yields a scripted stream from .chat()."""

    def __init__(self, scripts: list[list]):
        # `scripts` is a list of stream-iters, one per `chat()` call (multi-step support).
        self._scripts = list(scripts)
        self.calls = 0

    async def chat(self, messages, tools):
        items = self._scripts.pop(0) if self._scripts else []
        self.calls += 1
        for x in items:
            yield x


async def _make_ollama(kernel, file_agent_id=None):
    meta = {"handler_module": "ollama_backend.tools"}
    if file_agent_id is not None:
        meta["file_agent_id"] = file_agent_id
    rec = await kernel.send("core", {"type": "create_agent", **meta})
    return rec["id"]


async def test_reflect_includes_file_agent_id_and_no_history(seeded_kernel, file_agent):
    oid = await _make_ollama(seeded_kernel, file_agent)
    r = await seeded_kernel.send(oid, {"type": "reflect"})
    assert r["file_agent_id"] == file_agent
    assert "send" in r["verbs"]


async def test_send_requires_file_agent_id(seeded_kernel):
    oid = await _make_ollama(seeded_kernel)
    r = await seeded_kernel.send(oid, {"type": "send", "text": "hi"})
    assert "error" in r
    assert "file_agent_id" in r["error"]


async def test_history_requires_file_agent_id(seeded_kernel):
    oid = await _make_ollama(seeded_kernel)
    r = await seeded_kernel.send(oid, {"type": "history"})
    assert "error" in r


async def test_history_returns_messages(seeded_kernel, file_agent, tmp_path):
    oid = await _make_ollama(seeded_kernel, file_agent)
    # Pre-seed the default 'cli' client thread.
    chat = json.dumps(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    )
    await seeded_kernel.send(
        file_agent,
        {
            "type": "write",
            "path": f".fantastic/agents/{oid}/chat_cli.json",
            "content": chat,
        },
    )
    r = await seeded_kernel.send(oid, {"type": "history"})
    assert len(r["messages"]) == 2
    assert r["client_id"] == "cli"


async def test_history_per_client(seeded_kernel, file_agent, tmp_path):
    """Two clients = two separate threads; history reads only the asked-for one."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    # Seed two distinct chats.
    for cid, last in (("alice", "A-reply"), ("bob", "B-reply")):
        chat = json.dumps(
            [
                {"role": "user", "content": f"hi from {cid}"},
                {"role": "assistant", "content": last},
            ]
        )
        await seeded_kernel.send(
            file_agent,
            {
                "type": "write",
                "path": f".fantastic/agents/{oid}/chat_{cid}.json",
                "content": chat,
            },
        )
    a = await seeded_kernel.send(oid, {"type": "history", "client_id": "alice"})
    b = await seeded_kernel.send(oid, {"type": "history", "client_id": "bob"})
    assert a["messages"][-1]["content"] == "A-reply"
    assert b["messages"][-1]["content"] == "B-reply"
    assert a["client_id"] == "alice" and b["client_id"] == "bob"


async def test_run_no_tool_calls_returns_content(seeded_kernel, file_agent):
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider([["Hello! ", "How are you?"]])
    ot._providers[oid] = fp
    try:
        r = await seeded_kernel.send(oid, {"type": "send", "text": "hi"})
        assert r["final"] == "Hello! How are you?"
        assert fp.calls == 1
    finally:
        ot._providers.pop(oid, None)


async def test_run_with_tool_call_iterates(seeded_kernel, file_agent):
    """Model emits a tool_call to core, gets reply, second iteration finishes."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider(
        [
            # iter 1: emit tool_call
            [
                {
                    "tool_call": {
                        "id": "call_a",
                        "name": "send",
                        "arguments": {
                            "target_id": "core",
                            "payload": {"type": "list_agents"},
                        },
                    }
                }
            ],
            # iter 2: text only, loop ends
            ["Final answer based on tool reply."],
        ]
    )
    ot._providers[oid] = fp
    try:
        r = await seeded_kernel.send(oid, {"type": "send", "text": "list"})
        assert r["final"] == "Final answer based on tool reply."
        assert fp.calls == 2
    finally:
        ot._providers.pop(oid, None)


async def test_run_persists_history_via_file_agent(seeded_kernel, file_agent, tmp_path):
    """Default caller (no client_id) persists to chat_cli.json."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider([["reply"]])
    ot._providers[oid] = fp
    try:
        await seeded_kernel.send(oid, {"type": "send", "text": "hi"})
        path = tmp_path / ".fantastic" / "agents" / oid / "chat_cli.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data[-2] == {"role": "user", "content": "hi"}
        assert data[-1] == {"role": "assistant", "content": "reply"}
    finally:
        ot._providers.pop(oid, None)


async def test_run_persists_per_client_threads(seeded_kernel, file_agent, tmp_path):
    """Two client_ids → two distinct chat files, each with its own turns."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider([["A-reply"], ["B-reply"]])
    ot._providers[oid] = fp
    try:
        await seeded_kernel.send(
            oid, {"type": "send", "text": "hi A", "client_id": "alice"}
        )
        await seeded_kernel.send(
            oid, {"type": "send", "text": "hi B", "client_id": "bob"}
        )
        path_a = tmp_path / ".fantastic" / "agents" / oid / "chat_alice.json"
        path_b = tmp_path / ".fantastic" / "agents" / oid / "chat_bob.json"
        assert path_a.exists() and path_b.exists()
        a = json.loads(path_a.read_text())
        b = json.loads(path_b.read_text())
        assert a[-2]["content"] == "hi A" and a[-1]["content"] == "A-reply"
        assert b[-2]["content"] == "hi B" and b[-1]["content"] == "B-reply"
    finally:
        ot._providers.pop(oid, None)


async def test_unknown_verb_errors(seeded_kernel, file_agent):
    oid = await _make_ollama(seeded_kernel, file_agent)
    r = await seeded_kernel.send(oid, {"type": "garbage"})
    assert "error" in r


async def test_cli_caller_routes_to_cli_only(seeded_kernel, file_agent):
    """Default caller (client_id='cli') has events dispatched via
    kernel.send('cli', …) so cli's stdout handler runs. No leak to the
    backend's own inbox (which would broadcast to unrelated WS subscribers).
    """
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider([["chunk1 ", "chunk2"]])
    ot._providers[oid] = fp
    sends: list[tuple[str, dict]] = []
    emits: list[tuple[str, dict]] = []

    real_send, real_emit = seeded_kernel.send, seeded_kernel.emit

    async def spy_send(target, payload):
        sends.append((target, dict(payload)))
        return await real_send(target, payload)

    async def spy_emit(target, payload):
        emits.append((target, dict(payload)))
        return await real_emit(target, payload)

    try:
        with (
            patch.object(seeded_kernel, "send", spy_send),
            patch.object(seeded_kernel, "emit", spy_emit),
        ):
            await seeded_kernel.send(oid, {"type": "send", "text": "hi"})

        # cli received tokens via kernel.send (so its handler ran).
        cli_tokens = [p for t, p in sends if t == "cli" and p.get("type") == "token"]
        cli_done = [p for t, p in sends if t == "cli" and p.get("type") == "done"]
        assert len(cli_tokens) == 2
        assert len(cli_done) == 1
        # Backend's own inbox got NO stream events (cli routing only).
        own_stream = [
            p
            for t, p in emits
            if t == oid and p.get("type") in ("token", "say", "done")
        ]
        assert own_stream == [], f"unexpected leak to own inbox: {own_stream}"
        # Stream events carry client_id="cli".
        assert all(p.get("client_id") == "cli" for p in cli_tokens + cli_done)
    finally:
        ot._providers.pop(oid, None)


async def test_browser_caller_routes_to_own_inbox_only(seeded_kernel, file_agent):
    """Caller passes a non-cli client_id (e.g. browser uuid) → events
    emit to backend's own inbox tagged with client_id, NOT to cli.
    """
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider([["a", "b"]])
    ot._providers[oid] = fp
    sends: list[tuple[str, dict]] = []
    emits: list[tuple[str, dict]] = []

    real_send, real_emit = seeded_kernel.send, seeded_kernel.emit

    async def spy_send(target, payload):
        sends.append((target, dict(payload)))
        return await real_send(target, payload)

    async def spy_emit(target, payload):
        emits.append((target, dict(payload)))
        return await real_emit(target, payload)

    try:
        with (
            patch.object(seeded_kernel, "send", spy_send),
            patch.object(seeded_kernel, "emit", spy_emit),
        ):
            await seeded_kernel.send(
                oid, {"type": "send", "text": "hi", "client_id": "web_xyz"}
            )

        # Backend's own inbox got the stream, tagged with the web client_id.
        own_tokens = [p for t, p in emits if t == oid and p.get("type") == "token"]
        own_done = [p for t, p in emits if t == oid and p.get("type") == "done"]
        assert len(own_tokens) == 2
        assert len(own_done) == 1
        assert all(p["client_id"] == "web_xyz" for p in own_tokens + own_done)
        # cli got NO stream events (no leak across clients).
        cli_stream = [
            p
            for t, p in sends
            if t == "cli" and p.get("type") in ("token", "say", "done")
        ]
        assert cli_stream == [], f"cli leak: {cli_stream}"
    finally:
        ot._providers.pop(oid, None)


async def test_assemble_includes_agent_menu(seeded_kernel, file_agent):
    """System prompt carries a 'Available agents' menu built by reflecting
    on every running agent, plus a `send`-tool how-to. Each turn rebuilds
    the menu lazily; chat.json holds only user/assistant turns.
    """
    oid = await _make_ollama(seeded_kernel, file_agent)
    # Force a fresh menu build.
    ot._invalidate_menu(oid)
    msgs = await ot._assemble(oid, "hello", seeded_kernel, "alice")
    sys_block = msgs[0]["content"]
    assert "Available agents" in sys_block
    # File agent is in the menu (created by the file_agent fixture).
    assert file_agent in sys_block
    # Verbs are listed alongside ids.
    assert "read" in sys_block
    # Send-tool guidance present.
    assert "send tool" in sys_block.lower()
    assert "refresh_menu" in sys_block
    # Menu is now cached.
    assert oid in ot._menu_cache


async def test_menu_invalidates_after_tool_call(seeded_kernel, file_agent):
    """Successful tool_call clears the menu so the next assemble rebuilds it."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider(
        [
            # iter 1: emit a tool_call to core
            [
                {
                    "tool_call": {
                        "id": "call_a",
                        "name": "send",
                        "arguments": {
                            "target_id": "core",
                            "payload": {"type": "list_agents"},
                        },
                    }
                }
            ],
            # iter 2: text only, loop ends
            ["done."],
        ]
    )
    ot._providers[oid] = fp
    try:
        # Prime the cache.
        ot._menu_cache[oid] = [{"id": "stale", "sentence": "", "verbs": []}]
        await seeded_kernel.send(
            oid, {"type": "send", "text": "list", "client_id": "alice"}
        )
        # After the run, cache must be invalidated (popped).
        assert oid not in ot._menu_cache
    finally:
        ot._providers.pop(oid, None)


async def test_refresh_menu_verb_invalidates(seeded_kernel, file_agent):
    """LLM can self-clear the menu via send(<self>, {type:'refresh_menu'})."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    ot._menu_cache[oid] = [{"id": "stale", "sentence": "", "verbs": []}]
    r = await seeded_kernel.send(oid, {"type": "refresh_menu"})
    assert r == {"refreshed": True}
    assert oid not in ot._menu_cache


async def test_menu_not_persisted_to_chat_json(seeded_kernel, file_agent, tmp_path):
    """Menu lives in the system block ONLY — never written to chat_<client>.json."""
    oid = await _make_ollama(seeded_kernel, file_agent)
    fp = _FakeProvider([["reply"]])
    ot._providers[oid] = fp
    try:
        await seeded_kernel.send(
            oid, {"type": "send", "text": "hi", "client_id": "alice"}
        )
    finally:
        ot._providers.pop(oid, None)
    chat_path = tmp_path / ".fantastic" / "agents" / oid / "chat_alice.json"
    data = json.loads(chat_path.read_text())
    blob = json.dumps(data)
    # Persisted history is just user/assistant turns — none of the
    # menu prose, send-tool how-to, or substrate primer should leak in.
    assert "Available agents" not in blob
    assert "send tool" not in blob.lower()
    assert "Fantastic kernel" not in blob


async def test_contended_send_emits_queued_event(seeded_kernel, file_agent):
    """Second concurrent send arrives while the first holds the lock →
    backend emits a `queued` event tagged with the second caller's
    client_id. UI uses this to mark the message as waiting; first
    `token` for the same client_id implicitly clears the marker."""
    oid = await _make_ollama(seeded_kernel, file_agent)

    # First provider call sleeps so the second `send` finds the lock held.
    class _SlowFirst:
        def __init__(self):
            self.calls = 0

        async def chat(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(0.20)
            yield "ok"

    ot._providers[oid] = _SlowFirst()

    captured: list[tuple[str, dict]] = []
    real_send, real_emit = seeded_kernel.send, seeded_kernel.emit

    async def spy_send(target, payload):
        captured.append(("send", target, dict(payload)))
        return await real_send(target, payload)

    async def spy_emit(target, payload):
        captured.append(("emit", target, dict(payload)))
        return await real_emit(target, payload)

    try:
        with (
            patch.object(seeded_kernel, "send", spy_send),
            patch.object(seeded_kernel, "emit", spy_emit),
        ):
            t1 = asyncio.create_task(
                seeded_kernel.send(
                    oid, {"type": "send", "text": "first", "client_id": "alice"}
                )
            )
            await asyncio.sleep(0.05)  # let t1 acquire the lock
            t2 = asyncio.create_task(
                seeded_kernel.send(
                    oid, {"type": "send", "text": "second", "client_id": "bob"}
                )
            )
            r1, r2 = await asyncio.gather(t1, t2)

        assert r1["final"] == "ok" and r2["final"] == "ok"

        # Bob's request hit the lock → got a queued event tagged for bob.
        # Browser-routed events go via emit (target = oid).
        bob_queued = [
            p
            for kind, t, p in captured
            if kind == "emit"
            and t == oid
            and p.get("type") == "queued"
            and p.get("client_id") == "bob"
        ]
        assert len(bob_queued) == 1, (
            f"expected exactly one queued event for bob; got {len(bob_queued)}"
        )

        # Alice did NOT get queued (she acquired the lock first).
        alice_queued = [
            p
            for kind, t, p in captured
            if p.get("type") == "queued" and p.get("client_id") == "alice"
        ]
        assert alice_queued == []

        # Bob then got tokens (cli routing for client='cli'; otherwise
        # emit on agent's own inbox — bob is a non-cli client_id).
        bob_tokens = [
            p
            for kind, t, p in captured
            if kind == "emit"
            and t == oid
            and p.get("type") == "token"
            and p.get("client_id") == "bob"
        ]
        assert len(bob_tokens) >= 1
    finally:
        ot._providers.pop(oid, None)


async def test_concurrent_sends_serialize_per_backend(seeded_kernel, file_agent):
    """Two concurrent _send calls on the same backend → run sequentially
    via the per-backend asyncio.Lock. Verified by the order of provider
    invocations vs the order tasks finish.
    """
    oid = await _make_ollama(seeded_kernel, file_agent)

    in_flight = 0
    max_in_flight = 0
    order: list[str] = []

    class _SerialProvider:
        async def chat(self, messages, tools):
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            try:
                # Cooperative yield so a second caller WOULD overlap if
                # the lock weren't there. The test asserts overlap = 0.
                await asyncio.sleep(0.05)
                user = messages[-1]["content"]
                order.append(user)
                yield "ok"
            finally:
                in_flight -= 1

    ot._providers[oid] = _SerialProvider()
    try:
        results = await asyncio.gather(
            seeded_kernel.send(
                oid, {"type": "send", "text": "first", "client_id": "a"}
            ),
            seeded_kernel.send(
                oid, {"type": "send", "text": "second", "client_id": "b"}
            ),
        )
        assert max_in_flight == 1, f"saw {max_in_flight} concurrent generations"
        assert order == ["first", "second"], f"FIFO order broke: {order}"
        assert all(r["final"] == "ok" for r in results)
        assert {r["client_id"] for r in results} == {"a", "b"}
    finally:
        ot._providers.pop(oid, None)
