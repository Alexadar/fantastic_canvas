"""Tests for core.ai.config — load/save from .fantastic/ai/config.json."""

import json

from core.ai.config import load_config, save_config, _config_path


def test_config_path(project_dir):
    path = _config_path(project_dir)
    assert path == project_dir / ".fantastic" / "ai" / "config.json"


def test_load_config_missing(project_dir):
    assert load_config(project_dir) is None


def test_save_and_load(project_dir):
    config = {"provider": "ollama", "endpoint": "http://localhost:11434", "model": "llama3.2"}
    save_config(project_dir, config)
    loaded = load_config(project_dir)
    assert loaded == config


def test_save_creates_dirs(project_dir):
    save_config(project_dir, {"provider": "ollama"})
    assert _config_path(project_dir).exists()


def test_load_corrupted_json(project_dir):
    path = _config_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json {{{")
    assert load_config(project_dir) is None


def test_save_overwrites(project_dir):
    save_config(project_dir, {"provider": "ollama", "model": "a"})
    save_config(project_dir, {"provider": "ollama", "model": "b"})
    loaded = load_config(project_dir)
    assert loaded["model"] == "b"
