"""Terminal agent — spawns a PTY shell session."""

import os
from core.agent import autorun


@autorun(pty=True)
def main():
    shell = os.environ.get("SHELL", "/bin/sh")
    os.execlp(shell, shell, "-l")
