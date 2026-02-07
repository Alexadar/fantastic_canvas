"""Tests for core._paths — asset path resolution."""

from pathlib import Path

from core._paths import (
    _dev_root,
    bundled_agents_dir,
    claude_md_path,
    env_path,
    fantastic_md_path,
    skills_dir,
    web_dist_dir,
)


def test_dev_root_finds_repo():
    """In dev mode (repo has bundled_agents/), _dev_root returns a Path."""
    root = _dev_root()
    assert root is not None
    assert isinstance(root, Path)
    assert (root / "bundled_agents").is_dir()


def test_web_dist_dir_exists():
    path = web_dist_dir()
    assert isinstance(path, Path)
    # In dev mode with built frontend, this should exist
    assert path.exists()


def test_skills_dir():
    path = skills_dir()
    assert isinstance(path, Path)
    # May not exist in all setups


def test_bundled_agents_dir():
    path = bundled_agents_dir()
    assert isinstance(path, Path)
    # In dev mode, points to repo/bundled_agents
    assert path.name == "bundled_agents"


def test_claude_md_path():
    path = claude_md_path()
    assert path.name == "CLAUDE.md"
    assert path.exists()


def test_fantastic_md_path():
    path = fantastic_md_path()
    assert path.name == "fantastic.md"
    assert path.exists()


def test_env_path():
    result = env_path()
    # May or may not exist — just check type
    assert result is None or isinstance(result, Path)
