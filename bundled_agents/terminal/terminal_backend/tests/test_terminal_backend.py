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
    assert elapsed < 3.0  # timeout fired around 1s


async def test_shell_recovers_after_timeout(terminal):
    k, tid = terminal
    await k.send(tid, {"type": "shell", "cmd": "sleep 60", "timeout": 0.5})
    # next shell call should work — Ctrl-C was sent on timeout
    r = await k.send(tid, {"type": "shell", "cmd": "echo recovered"})
    assert r["completed"] is True
    assert "recovered" in r["output"]


async def test_shell_silently_ignores_unknown_args(terminal):
    """Failfast on parameters we explicitly reject is overkill — kwargs
    we don't read are just ignored."""
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


async def test_write_large_paste_not_truncated(terminal):
    """Drift guard for the terminal-dead-after-paste bug: the PTY fd is
    non-blocking, so a single os.write() short-writes anything bigger
    than the PTY input buffer and silently drops the tail. `_write`
    must loop until every byte lands. Write a payload far larger than
    any PTY buffer and assert the whole thing arrives intact (`written`
    == full length, and the head AND tail both echo back)."""
    k, tid = terminal
    # 64 KB — well past a typical PTY input buffer (a few KB).
    body = "".join(f"L{i:05d}" for i in range(8000))  # ~64000 chars
    payload = "echo START_" + body + "_END\n"
    r = await k.send(tid, {"type": "write", "data": payload})
    assert r["written"] == len(payload.encode("utf-8")), (
        f"short write: {r['written']} of {len(payload.encode('utf-8'))}"
    )
    await asyncio.sleep(1.0)
    out = await k.send(tid, {"type": "output"})
    # Both ends echo → nothing was dropped mid-stream.
    assert "START_L00000" in out["output"]
    assert "L07999_END" in out["output"]


async def test_flow_control_pauses_and_resumes(terminal):
    """VSCode-style backpressure (FlowControlConstants, ported): once
    emitted output outruns the streaming consumer's acks past
    HIGH_WATERMARK, the PTY reader detaches ('paused'); the `ack` verb
    re-attaches it once the backlog drains below LOW_WATERMARK.
    Without it a flood of output piles unbounded emit tasks onto the
    loop and the tab locks up — the 'terminal dead after paste'
    failure mode for any paste that runs a noisy command."""
    k, tid = terminal
    # Flood the PTY with well over HIGH_WATERMARK (100K) chars of
    # output. `head -c` caps it so the child exits cleanly even if we
    # never resumed; the pipe stalls behind backpressure meanwhile.
    await k.send(
        tid,
        {"type": "write", "data": "yes FANTASTIC_FLOW_CONTROL | head -c 400000\n"},
    )
    refl = None
    for _ in range(60):
        await asyncio.sleep(0.05)
        refl = await k.send(tid, {"type": "reflect"})
        if refl["paused"]:
            break
    assert refl["paused"] is True, "reader must pause once unacked > HIGH_WATERMARK"
    assert refl["unacked"] > 100_000
    # Ack the backlog down — the reader must re-attach and keep draining.
    r = None
    for _ in range(200):
        r = await k.send(tid, {"type": "ack", "chars": 5000})
        if not r["paused"]:
            break
    assert r["paused"] is False, "reader must re-attach once unacked < LOW_WATERMARK"
    assert r["unacked"] < 5_000


async def test_ack_on_unpaused_terminal_is_harmless(terminal):
    """An ack from a streamer that never hit the watermark just floors
    the counter at zero — no negative drift, stays unpaused."""
    k, tid = terminal
    r = await k.send(tid, {"type": "ack", "chars": 999999})
    assert r["unacked"] == 0
    assert r["paused"] is False


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


async def test_shutdown_kills_pty_via_delete_agent(seeded_kernel):
    """End-to-end: when core.delete_agent runs, terminal_backend's
    `shutdown` verb must fire and tear down the PTY. Without this hook
    the subprocess outlives its agent record and keeps emitting output
    to a dead inbox (visible as ghost sprites in telemetry views).

    We assert two things:
      1. `_procs` no longer has an entry for the agent id (the
         in-memory state was cleared).
      2. waitpid finds the child reaped or reapable (SIGKILL landed).
         os.kill(pid, 0) is unreliable on macOS — zombies report
         alive until the parent waits — so we use waitpid which
         reaps and tells us the child terminated.
    """
    import asyncio
    import os

    from terminal_backend.tools import _procs

    rec = await seeded_kernel.send(
        "core",
        {"type": "create_agent", "handler_module": "terminal_backend.tools"},
    )
    tid = rec["id"]
    state = _procs.get(tid)
    assert state and state.get("pid"), "boot should spawn a PTY"
    pid = state["pid"]
    r = await seeded_kernel.send("core", {"type": "delete_agent", "id": tid})
    assert r.get("deleted") is True
    assert tid not in _procs, "shutdown must drop the _procs entry"
    # Reap the child. waitpid returns (pid, status) once the child
    # has exited; on macOS this is the reliable liveness probe (kill
    # -0 reports success for un-reaped zombies).
    reaped = (0, 0)
    for _ in range(20):
        try:
            reaped = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            # Already reaped by another path — counts as success.
            reaped = (pid, 0)
            break
        if reaped[0] == pid:
            break
        await asyncio.sleep(0.05)
    assert reaped[0] == pid, f"PTY pid {pid} not reaped after shutdown"
