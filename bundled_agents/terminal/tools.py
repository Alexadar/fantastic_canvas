"""Terminal bundle — scrollback, restart, signal, and terminal handbook tools."""

from pathlib import Path

from core.dispatch import ToolResult
from core.tools._process import (
    _process_output, _process_restart, _process_signal,
)

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


async def _get_handbook_terminal(skill: str = "") -> ToolResult:
    if skill:
        skill_file = _SKILLS_DIR / f"{skill}.md"
        if skill_file.exists():
            return ToolResult(data={"text": f"# SKILL: {skill}\n\n{skill_file.read_text()}"})
        available = [p.stem for p in _SKILLS_DIR.glob("*.md")] if _SKILLS_DIR.exists() else []
        avail_str = ", ".join(sorted(available)) or "(none)"
        return ToolResult(data={"error": f"Skill '{skill}' not found. Available: {avail_str}"})
    available = sorted(p.stem for p in _SKILLS_DIR.glob("*.md")) if _SKILLS_DIR.exists() else []
    return ToolResult(data={"text": "Terminal skills: " + ", ".join(available) if available else "No terminal skills found."})


def _register_server_hooks(engine, process_runner):
    """Register terminal REST endpoints via server hooks."""
    from core.server._state import register_route_hook
    from core.dispatch import dispatch

    def _terminal_routes(app, state):
        from fastapi import HTTPException

        @app.post("/api/terminal/{agent_id}/write")
        async def terminal_write(agent_id: str, body: dict):
            data = body.get("data", "")
            if not state.process_runner or not state.process_runner.exists(agent_id):
                return {"error": "process not found", "agent_id": agent_id}
            await state.process_runner.write(agent_id, data)
            return {"ok": True, "wrote": len(data)}

        @app.get("/api/terminal/{agent_id}/output")
        async def terminal_output_rest(agent_id: str, max_lines: int = 200):
            tr = await dispatch("process_output", agent_id=agent_id, max_lines=max_lines)
            if "error" in tr.data:
                return {"output": "", "lines": 0}
            return tr.data

        @app.post("/api/terminal/{agent_id}/restart")
        async def terminal_restart_rest(agent_id: str):
            from core.server import broadcast
            tr = await dispatch("process_restart", agent_id=agent_id)
            if "error" in tr.data:
                raise HTTPException(status_code=404, detail=tr.data["error"])
            for m in tr.broadcast:
                await broadcast(m)
            return {"ok": True}

        @app.post("/api/terminal/{agent_id}/signal")
        async def terminal_send_signal(agent_id: str, body: dict):
            sig = body.get("signal", 2)
            tr = await dispatch("process_signal", agent_id=agent_id, signal=sig)
            if "error" in tr.data:
                raise HTTPException(status_code=404, detail=tr.data["error"])
            return {"ok": True}

    register_route_hook(_terminal_routes)


def register_dispatch():
    """Return inner dispatch functions for _DISPATCH table."""
    return {
        "get_handbook_terminal": _get_handbook_terminal,
        # Terminal-named aliases → generic process functions (for tool wrapper dispatch)
        "terminal_output": _process_output,
        "terminal_restart": _process_restart,
        "terminal_signal": _process_signal,
    }


def register_tools(engine, fire_broadcasts, process_runner=None):
    """Register terminal tools + server REST endpoints."""
    tools = {}

    # ─── Server hooks: terminal REST endpoints ──
    _register_server_hooks(engine, process_runner)

    async def terminal_output(agent_id: str, max_lines: int = 200) -> str:
        """Read terminal scrollback output.

        Args:
            agent_id: The terminal's agent ID.
            max_lines: Maximum number of lines to return (default 200).
        """
        tr = await _process_output(agent_id=agent_id, max_lines=max_lines)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return tr.data["output"]
    tools["terminal_output"] = terminal_output

    async def terminal_restart(agent_id: str) -> str:
        """Restart a terminal process with the same parameters.

        Kills the current process and re-forks with the original command/args.
        The terminal keeps the same ID so the frontend reconnects seamlessly.

        Args:
            agent_id: The terminal's agent ID.
        """
        tr = await _process_restart(agent_id=agent_id)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        await fire_broadcasts(tr)
        return f"Terminal {agent_id} restarted"
    tools["terminal_restart"] = terminal_restart

    async def terminal_signal(agent_id: str, signal: int = 2) -> str:
        """Send a signal to a terminal's process.

        Args:
            agent_id: The terminal's agent ID.
            signal: Signal number (default 2=SIGINT). Common: 2=SIGINT, 15=SIGTERM.
        """
        tr = await _process_signal(agent_id=agent_id, signal=signal)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return f"Signal {signal} sent to terminal {agent_id}"
    tools["terminal_signal"] = terminal_signal

    async def get_handbook_terminal(skill: str = "") -> str:
        """Get terminal plugin handbook.

        Without arguments: lists available terminal skills.
        With skill name: returns that specific skill doc.

        Available skills: terminal-control

        Examples:
            get_handbook_terminal()                          # list skills
            get_handbook_terminal(skill="terminal-control")  # full doc
        """
        tr = await _get_handbook_terminal(skill)
        if "error" in tr.data:
            return f"[ERROR] {tr.data['error']}"
        return tr.data["text"]
    tools["get_handbook_terminal"] = get_handbook_terminal

    return tools
