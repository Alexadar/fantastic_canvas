"""terminal_backend — PTY shell session."""

from __future__ import annotations

import asyncio
import time

import pytest


async def _make_terminal(kernel, command="/bin/sh"):
    rec = await kernel.send(
        "core",
        {
            "type": "create_agent",
            "handler_module": "terminal_backend.tools",
            "command": command,
        },
    )
    # core auto-boots; give the PTY a moment to spawn
    await asyncio.sleep(0.3)
    return rec["id"]


@pytest.fixture
async def terminal(seeded_kernel):
    tid = await _make_terminal(seeded_kernel)
    yield seeded_kernel, tid
    # cleanup
    await seeded_kernel.send(tid, {"type": "stop"})


async def test_reflect(terminal):
    k, tid = terminal
    r = await k.send(tid, {"type": "reflect"})
    assert r["sentence"].startswith("PTY")
    assert r["running"] is True
    assert r["cols"] >= 40


async def test_shell_done_token_fast_command(terminal):
    k, tid = terminal
    t0 = time.time()
    r = await k.send(tid, {"type": "shell", "cmd": "echo hello-world"})
    elapsed = time.time() - t0
    assert r["completed"] is True
    assert "hello-world" in r["output"]
    # should be much faster than 30s default timeout
    assert elapsed < 5.0


async def test_shell_timeout(terminal):
    k, tid = terminal
    t0 = time.time()
    r = await k.send(tid, {"type": "shell", "cmd": "sleep 60", "timeout": 1.0})
    elapsed = time.time() - t0
    assert r["completed"] is False
    assert r["error"] == "timeout"
    assert elapsed < 3.0   # timeout fired around 1s


async def test_shell_recovers_after_timeout(terminal):
    k, tid = terminal
    await k.send(tid, {"type": "shell", "cmd": "sleep 60", "timeout": 0.5})
    # next shell call should work — Ctrl-C was sent on timeout
    r = await k.send(tid, {"type": "shell", "cmd": "echo recovered"})
    assert r["completed"] is True
    assert "recovered" in r["output"]


async def test_shell_silently_ignores_unknown_args(terminal):
    """Failfast on parameters we explicitly reject is overkill — kwargs
    we don't read are just ignored. `wait` (legacy) goes through cleanly."""
    k, tid = terminal
    r = await k.send(tid, {"type": "shell", "cmd": "echo silently_ok", "wait": 999})
    assert r["completed"] is True
    assert "silently_ok" in r["output"]


async def test_shell_requires_cmd(terminal):
    k, tid = terminal
    r = await k.send(tid, {"type": "shell"})
    assert "error" in r


async def test_write_delivers_bytes(terminal):
    k, tid = terminal
    r = await k.send(tid, {"type": "write", "data": "echo hi-via-write\n"})
    assert r["written"] > 0
    await asyncio.sleep(0.4)
    out = await k.send(tid, {"type": "output"})
    assert "hi-via-write" in out["output"]


async def test_resize(terminal):
    k, tid = terminal
    r = await k.send(tid, {"type": "resize", "cols": 100, "rows": 30})
    assert r["resized"] is True
    refl = await k.send(tid, {"type": "reflect"})
    assert refl["cols"] == 100
    assert refl["rows"] == 30


async def test_shell_without_boot_errors(seeded_kernel):
    rec = await seeded_kernel.send(
        "core",
        {"type": "create_agent", "handler_module": "terminal_backend.tools"},
    )
    # core auto-boots, so manually stop first
    await seeded_kernel.send(rec["id"], {"type": "stop"})
    r = await seeded_kernel.send(rec["id"], {"type": "shell", "cmd": "echo x"})
    assert "error" in r
    assert "not running" in r["error"]


async def test_unknown_verb_errors(terminal):
    k, tid = terminal
    r = await k.send(tid, {"type": "garbage"})
    assert "error" in r
