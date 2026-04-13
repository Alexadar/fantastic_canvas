"""Terminal bundle — scrollback, restart, signal, and terminal handbook tools."""

from pathlib import Path

from core.dispatch import ToolResult
from core.tools._process import (
    _process_output,
    _process_restart,
    _process_signal,
)

NAME = "terminal"

_SKILLS_DIR = Path(__file__).resolve().parent / "skills"


async def _get_handbook_terminal(skill: str = "") -> ToolResult:
    if skill:
        skill_file = _SKILLS_DIR / f"{skill}.md"
        if skill_file.exists():
            return ToolResult(
                data={"text": f"# SKILL: {skill}\n\n{skill_file.read_text()}"}
            )
        available = (
            [p.stem for p in _SKILLS_DIR.glob("*.md")] if _SKILLS_DIR.exists() else []
        )
        avail_str = ", ".join(sorted(available)) or "(none)"
        return ToolResult(
            data={"error": f"Skill '{skill}' not found. Available: {avail_str}"}
        )
    available = (
        sorted(p.stem for p in _SKILLS_DIR.glob("*.md")) if _SKILLS_DIR.exists() else []
    )
    return ToolResult(
        data={
            "text": "Terminal skills: " + ", ".join(available)
            if available
            else "No terminal skills found."
        }
    )


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
