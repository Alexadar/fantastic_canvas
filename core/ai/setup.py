"""Interactive AI setup wizard — arrow-key TUI for provider/model config.

Up/Down: navigate rows
Left/Right: cycle options within a row
Enter: save and exit
Esc/q: cancel
"""

from __future__ import annotations

import asyncio
import sys
import termios
import tty
from pathlib import Path
from typing import Callable

from .. import conversation
from .config import save_config
from .ollama_provider import OllamaProvider, DEFAULT_ENDPOINT
from .provider import DiscoverResult

# ANSI helpers
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
CLEAR_LINE = "\033[2K"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
UP = "\033[A"


# Popular models to suggest for pulling (if not already available)
SUGGESTED_MODELS = [
    ("llama3.2", "3B general-purpose"),
    ("llama3.2:1b", "1B lightweight"),
    ("mistral", "7B general-purpose"),
    ("gemma2:2b", "2B lightweight"),
    ("qwen2.5:3b", "3B multilingual"),
    ("deepseek-r1:8b", "8B reasoning"),
]


class _Row:
    """A navigable row with left/right options."""

    def __init__(self, label: str, options: list[str], descriptions: list[str] | None = None):
        self.label = label
        self.options = options
        self.descriptions = descriptions or [""] * len(options)
        self.selected = 0

    def left(self):
        if self.options:
            self.selected = (self.selected - 1) % len(self.options)

    def right(self):
        if self.options:
            self.selected = (self.selected + 1) % len(self.options)

    @property
    def value(self) -> str:
        return self.options[self.selected] if self.options else ""

    @property
    def description(self) -> str:
        return self.descriptions[self.selected] if self.descriptions else ""


def _read_key() -> str:
    """Read a single keypress, handling escape sequences."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(ch3, "")
            return "esc"
        if ch == "\r" or ch == "\n":
            return "enter"
        if ch == "q":
            return "esc"
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _render(rows: list[_Row], current: int, total_lines: int, status: str = ""):
    """Render the TUI, overwriting previous output."""
    # Move cursor up to overwrite previous render
    if total_lines > 0:
        sys.stdout.write(f"\033[{total_lines}A")

    lines = []

    for i, row in enumerate(rows):
        is_active = i == current
        prefix = conversation.AI_COLOR + ">" + RESET if is_active else " "
        label = f"{BOLD}{row.label}{RESET}" if is_active else f"{DIM}{row.label}{RESET}"

        # Build option chips
        chips = []
        for j, opt in enumerate(row.options):
            if j == row.selected:
                chip = f" {conversation.AI_COLOR}{BOLD}[{opt}]{RESET} "
            else:
                chip = f" {DIM}{opt}{RESET} "
            chips.append(chip)

        option_str = "".join(chips)
        desc = f"  {DIM}{row.description}{RESET}" if row.description and is_active else ""

        lines.append(f"{CLEAR_LINE}{prefix} {label}: {option_str}{desc}")

    # Action row
    save_label = f"{conversation.AI_COLOR}{BOLD}[ Save ]{RESET}" if current == len(rows) else f"{DIM}[ Save ]{RESET}"
    cancel_label = f"  {DIM}Esc to cancel{RESET}"
    lines.append(f"{CLEAR_LINE}  {save_label}{cancel_label}")

    if status:
        lines.append(f"{CLEAR_LINE}  {status}")
    else:
        lines.append(CLEAR_LINE)

    output = "\n".join(lines)
    sys.stdout.write(output)
    sys.stdout.flush()

    return len(lines)


async def run_setup(project_dir: Path, say_fn: Callable[[str], None] | None = None) -> bool:
    """Run interactive setup. Returns True if config was saved."""

    def say(msg: str):
        if say_fn:
            say_fn(msg)
        entry = conversation.say("fantastic", msg)
        print(conversation.format_entry(entry))

    # Probe Ollama
    say("probing AI providers...")
    result: DiscoverResult = await OllamaProvider.discover()

    if not result.available:
        say(f"ollama not available: {result.error}")
        say("install from https://ollama.ai then run: ai setup")
        return False

    # Build rows
    provider_row = _Row("Provider", ["ollama"], ["local LLM server"])

    # Model options: available models + suggested pulls
    available = result.models or []
    pull_candidates = [
        (name, desc) for name, desc in SUGGESTED_MODELS
        if name not in available
    ]

    model_names = list(available)
    model_descs = ["installed"] * len(available)
    for name, desc in pull_candidates:
        model_names.append(f"+ {name}")
        model_descs.append(f"pull {desc}")

    if not model_names:
        # Nothing available and nothing to suggest — shouldn't happen
        model_names = ["llama3.2"]
        model_descs = ["will pull"]

    model_row = _Row("Model", model_names, model_descs)

    rows = [provider_row, model_row]
    current = 0
    total_rows = len(rows) + 1  # +1 for save row
    rendered_lines = 0
    status = ""

    print()
    sys.stdout.write(HIDE_CURSOR)
    try:
        rendered_lines = _render(rows, current, 0, status)

        loop = asyncio.get_event_loop()
        while True:
            key = await loop.run_in_executor(None, _read_key)

            if key == "esc":
                sys.stdout.write(f"\n{SHOW_CURSOR}")
                sys.stdout.flush()
                say("setup cancelled")
                return False

            if key == "up":
                current = max(0, current - 1)
            elif key == "down":
                current = min(total_rows - 1, current + 1)
            elif key == "left" and current < len(rows):
                rows[current].left()
            elif key == "right" and current < len(rows):
                rows[current].right()
            elif key == "enter":
                if current == len(rows):
                    # Save
                    break
                else:
                    # Move to next row on enter
                    current = min(total_rows - 1, current + 1)

            rendered_lines = _render(rows, current, rendered_lines, status)

    finally:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.flush()

    # Process selection
    model_choice = model_row.value
    needs_pull = model_choice.startswith("+ ")
    model_name = model_choice.lstrip("+ ")

    print()

    if needs_pull:
        say(f"pulling {model_name}...")
        provider = OllamaProvider(endpoint=result.endpoint, model=model_name)
        try:
            last_status = ""
            async for progress in provider.pull(model_name):
                if progress != last_status:
                    sys.stdout.write(f"\r{CLEAR_LINE}  {conversation.AI_COLOR}{progress}{RESET}")
                    sys.stdout.flush()
                    last_status = progress
            print()
            say(f"pulled {model_name}")
        except Exception as e:
            print()
            say(f"pull failed: {e}")
            return False

    # Save config
    config = {
        "provider": provider_row.value,
        "endpoint": result.endpoint,
        "model": model_name,
    }
    save_config(project_dir, config)
    say(f"saved: {provider_row.value} / {model_name}")

    return True
