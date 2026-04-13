"""Conversation ring buffer + color formatting.

The conversation buffer ({who}:{message}) is the universal backbone.
Color-coded: core=magenta, user=green, agent/bundle=cyan.
Snapchat-style block layout: blank line, bold name, blank line, body
lines prefixed with a colored vertical bar, blank line.
"""

import shutil
import textwrap
from collections import deque
from datetime import datetime, timezone

CONVERSATION_BUFFER_SIZE = 1000

# ANSI color codes
CORE_COLOR = "\033[35m"  # magenta
USER_COLOR = "\033[32m"  # green
AGENT_COLOR = "\033[36m"  # cyan
AI_COLOR = "\033[33m"  # yellow
BOLD = "\033[1m"
RESET = "\033[0m"

# Full-block vertical bar, matches the banner glyph in core/cli.py.
BAR = "█"

CORE_ACTORS = {"fantastic", "system"}

_buffer: deque[dict] = deque(maxlen=CONVERSATION_BUFFER_SIZE)


def _term_width() -> int:
    return shutil.get_terminal_size((80, 24)).columns


def say(who: str, message: str) -> dict:
    """Append {ts, who, message} to the conversation buffer."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "who": who,
        "message": message,
    }
    _buffer.append(entry)
    return entry


def read(max_lines: int = 100) -> list[dict]:
    """Return the last N entries from the buffer."""
    n = min(max_lines, len(_buffer))
    return list(_buffer)[-n:]


def clear():
    """Clear the conversation buffer."""
    _buffer.clear()


def actor_color(who: str) -> str:
    """Return ANSI color for a given actor."""
    if who.lower() in CORE_ACTORS:
        return CORE_COLOR
    if who.lower() == "user":
        return USER_COLOR
    if who.lower() == "ai":
        return AI_COLOR
    return AGENT_COLOR


def format_entry(entry: dict) -> str:
    """Snapchat-style block renderer.

    Layout per entry:
      (blank line)
      {color+bold}{who}{reset}
      (blank line)
      {color}█{reset} body line 1
      {color}█{reset} body line 2

    Body lines wrap at terminal width minus the 2-char bar gutter.
    """
    color = actor_color(entry["who"])
    who = entry["who"]
    body = str(entry.get("message", ""))
    width = max(20, _term_width() - 2)

    lines: list[str] = []
    for paragraph in body.splitlines() or [""]:
        if paragraph == "":
            lines.append("")
            continue
        wrapped = textwrap.wrap(paragraph, width=width)
        lines.extend(wrapped or [""])

    header = f"{color}{BOLD}{who}{RESET}"
    body_rendered = "\n".join(f"{color}{BAR}{RESET} {line}" for line in lines)
    return f"\n{header}\n\n{body_rendered}\n"
