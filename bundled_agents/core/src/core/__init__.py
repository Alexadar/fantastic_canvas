"""core — userland orchestrator agent.

Lives at id="core" as the substrate's tree root. No handler_module —
root is a hollow tree container; the substrate handles all dispatch.

Composes a stdout-renderer child when stdin is a tty; otherwise
runs silent. `.run()` hands argv to `kernel.dispatch_argv` for mode
execution.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kernel import Agent, Kernel, dispatch_argv


class Core(Agent):
    """The userland root agent. Composes Cli when interactive."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        argv: list[str],
        root_path: Path | str = Path(".fantastic"),
    ) -> None:
        super().__init__(
            id="core",
            root_path=Path(root_path),
            ctx=kernel,
        )
        self.argv = argv
        if sys.stdin.isatty():
            # Cli is ephemeral — composed per-process, never persisted.
            from cli import Cli

            Cli(self.ctx, parent=self)

    async def run(self) -> None:
        await dispatch_argv(self.ctx, self.argv)
