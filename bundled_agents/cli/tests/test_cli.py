"""cli bundle — terminal output renderer."""

from __future__ import annotations


async def test_token_writes_to_stdout(seeded_kernel, capsys):
    await seeded_kernel.send("cli", {"type": "token", "text": "hello"})
    captured = capsys.readouterr()
    assert "hello" in captured.out


async def test_done_writes_newline(seeded_kernel, capsys):
    await seeded_kernel.send("cli", {"type": "done"})
    captured = capsys.readouterr()
    assert captured.out.endswith("\n")


async def test_say_with_source_prefix(seeded_kernel, capsys):
    await seeded_kernel.send(
        "cli", {"type": "say", "text": "hello", "source": "agent_x"}
    )
    captured = capsys.readouterr()
    assert "[agent_x]" in captured.out
    assert "hello" in captured.out


async def test_say_without_source(seeded_kernel, capsys):
    await seeded_kernel.send("cli", {"type": "say", "text": "no-source"})
    captured = capsys.readouterr()
    assert "no-source" in captured.out


async def test_error_writes_error_prefix(seeded_kernel, capsys):
    await seeded_kernel.send("cli", {"type": "error", "text": "boom"})
    captured = capsys.readouterr()
    assert "ERROR" in captured.out
    assert "boom" in captured.out


async def test_unknown_type_returns_none(seeded_kernel):
    r = await seeded_kernel.send("cli", {"type": "garbage"})
    assert r is None
