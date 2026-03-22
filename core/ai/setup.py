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
from .integrated_provider import IntegratedProvider
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

    # Probe all providers
    say("probing AI providers...")

    providers: list[str] = []
    provider_descs: list[str] = []
    provider_results: dict[str, DiscoverResult] = {}

    # Probe integrated first (default)
    lt_result = await IntegratedProvider.discover()
    if lt_result.available:
        providers.append("integrated")
        provider_descs.append("HuggingFace local model (default)")
        provider_results["integrated"] = lt_result

    # Probe Ollama
    ollama_result = await OllamaProvider.discover()
    if ollama_result.available:
        providers.append("ollama")
        provider_descs.append("Ollama local LLM server")
        provider_results["ollama"] = ollama_result

    if not providers:
        say("no AI providers available.")
        say("install torch+transformers or Ollama, then run: ai setup")
        return False

    # Build rows
    provider_row = _Row("Provider", providers, provider_descs)

    # Collect all models from all providers
    all_models: list[str] = []
    for name in providers:
        all_models.extend(provider_results[name].models)
    available = all_models or []
    if not available:
        say("no models available. Run: ollama pull <model>")
        return False

    model_row = _Row("Model", available)

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

    print()

    # Save config
    chosen_provider = provider_row.value
    chosen_result = provider_results.get(chosen_provider)
    config = {
        "provider": chosen_provider,
        "endpoint": chosen_result.endpoint if chosen_result else "",
        "model": model_row.value,
    }
    save_config(project_dir, config)
    say(f"saved: {provider_row.value} / {model_row.value}")

    return True
