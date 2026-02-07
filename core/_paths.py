"""Resolve asset paths. Works in dev (repo root) and pip-installed (_bundled/) mode."""

from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_BUNDLED = _THIS_DIR / "_bundled"


def _dev_root() -> Path | None:
    """Find repo root (has bundled_agents/ dir)."""
    candidate = _THIS_DIR.parent  # core/../ = repo root
    if (candidate / "bundled_agents").exists():
        return candidate
    return None


def web_dist_dir() -> Path:
    """Find web UI dist dir. Scans bundled_agents/*/web/dist/ for any bundle with a web UI."""
    root = _dev_root()
    if root:
        for d in sorted((root / "bundled_agents").iterdir()):
            candidate = d / "web" / "dist"
            if candidate.exists():
                return candidate
    return _BUNDLED / "web_dist"


def skills_dir() -> Path:
    root = _dev_root()
    if root:
        return root / "skills"
    return _BUNDLED / "skills"


def claude_md_path() -> Path:
    root = _dev_root()
    if root:
        return root / "CLAUDE.md"
    return _BUNDLED / "CLAUDE.md"


def fantastic_md_path() -> Path:
    root = _dev_root()
    if root:
        return root / "fantastic.md"
    return _BUNDLED / "fantastic.md"


def bundled_agents_dir() -> Path:
    """Find bundled_agents/ directory (dev mode) or _bundled/agents/ (pip)."""
    root = _dev_root()
    if root:
        return root / "bundled_agents"
    return _BUNDLED / "agents"


def default_shell_path() -> Path:
    root = _dev_root()
    if root:
        return root / "core" / "default_shell.html"
    return _BUNDLED / "default_shell.html"


def env_path() -> Path | None:
    """Find .env file — repo root in dev, project dir otherwise."""
    root = _dev_root()
    if root:
        p = root / ".env"
        if p.exists():
            return p
    return None
