"""Tests for AI command parsing in CoreRecipient."""

from core.recipients import CoreRecipient


def test_ai_default_status():
    r = CoreRecipient()
    assert r.parse("ai") == ("ai_status", {})


def test_ai_status():
    r = CoreRecipient()
    assert r.parse("ai status") == ("ai_status", {})


def test_ai_setup():
    r = CoreRecipient()
    assert r.parse("ai setup") == ("ai_setup", {})


def test_ai_models():
    r = CoreRecipient()
    assert r.parse("ai models") == ("ai_models", {})


def test_ai_model_set():
    r = CoreRecipient()
    assert r.parse("ai model llama3.2") == ("ai_model", {"model": "llama3.2"})


def test_ai_pull():
    r = CoreRecipient()
    assert r.parse("ai pull qwen2.5") == ("ai_pull", {"model": "qwen2.5"})


def test_ai_case_insensitive():
    r = CoreRecipient()
    assert r.parse("AI status") == ("ai_status", {})
    assert r.parse("AI MODELS") == ("ai_models", {})
