"""Tests for context window detection, estimation, and compaction."""

from core.ai.brain import AIBrain
from core.ai.provider import DiscoverResult


# ─── Token estimation ─────────────────────────────────────────────


def test_estimate_tokens_simple():
    msgs = [{"role": "user", "content": "hello world"}]  # 11 chars → 2 tokens
    assert AIBrain._estimate_tokens(msgs) == 11 // 4


def test_estimate_tokens_multiple():
    msgs = [
        {"role": "system", "content": "a" * 400},
        {"role": "user", "content": "b" * 100},
    ]
    assert AIBrain._estimate_tokens(msgs) == 500 // 4


def test_estimate_tokens_with_tool_calls():
    msgs = [{
        "role": "assistant",
        "content": "ok",
        "tool_calls": [{"function": {"name": "list_agents", "arguments": '{"parent": ""}'}}],
    }]
    tokens = AIBrain._estimate_tokens(msgs)
    assert tokens > 0


def test_estimate_tokens_empty():
    assert AIBrain._estimate_tokens([]) == 0


# ─── Budget calculation ───────────────────────────────────────────


def test_get_budget_with_provider(tmp_path):
    from unittest.mock import MagicMock
    brain = AIBrain(tmp_path)
    mock_provider = MagicMock()
    mock_provider.context_length = 32000
    brain._provider = mock_provider
    assert brain._get_budget() == 32000 - 2048


def test_get_budget_no_provider(tmp_path):
    brain = AIBrain(tmp_path)
    assert brain._get_budget() == 8192 - 2048


def test_get_budget_zero_context(tmp_path):
    from unittest.mock import MagicMock
    brain = AIBrain(tmp_path)
    mock_provider = MagicMock()
    mock_provider.context_length = 0
    brain._provider = mock_provider
    assert brain._get_budget() == 8192 - 2048  # falls back to default


# ─── Dynamic message truncation ──────────────────────────────────


def test_build_messages_truncates_to_budget(tmp_path):
    """Long history gets truncated to fit budget."""
    from core import conversation
    brain = AIBrain(tmp_path)
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.context_length = 1000  # very small
    brain._provider = mock

    # Fill conversation with many long messages
    conversation.clear()
    for i in range(50):
        conversation.say("user", f"message {i} " + "x" * 200)
        conversation.say("ai", f"response {i} " + "y" * 200)

    messages = brain._build_messages("current input")

    # Should have at least system + current input
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "current input"
    # Should not include all 100 history messages
    assert len(messages) < 100
    conversation.clear()


def test_build_messages_includes_recent_first(tmp_path):
    """Most recent messages should be kept, older ones dropped."""
    from core import conversation
    brain = AIBrain(tmp_path)
    from unittest.mock import MagicMock
    mock = MagicMock()
    mock.context_length = 4000  # tight budget — fits recent but not all
    brain._provider = mock

    conversation.clear()
    conversation.say("user", "old message " + "x" * 500)
    conversation.say("ai", "old response " + "y" * 500)
    conversation.say("user", "recent message")
    conversation.say("ai", "recent response")

    messages = brain._build_messages("now")
    contents = [m["content"] for m in messages if m["role"] in ("user", "assistant")]
    # Recent messages should be present
    assert any("recent" in c for c in contents)
    conversation.clear()


# ─── Compaction ───────────────────────────────────────────────────


def test_compact_messages_truncates_tool_results():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "do stuff"},
        {"role": "assistant", "content": "ok", "tool_calls": [{"function": {"name": "t", "arguments": "{}"}}]},
        {"role": "tool", "content": "x" * 500},  # long tool result — in middle, should be truncated
        {"role": "assistant", "content": "mid"},
        {"role": "tool", "content": "y" * 500},  # in tail — preserved
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "latest"},
        {"role": "assistant", "content": "final"},
    ]
    compacted = AIBrain._compact_messages(messages, 1000)
    # First tool result (middle) should be truncated
    middle_tools = [m for m in compacted[1:-4] if m["role"] == "tool"]
    for m in middle_tools:
        assert len(m["content"]) <= 220


def test_compact_messages_preserves_tail():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "tool", "content": "x" * 500},
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": "recent q"},
        {"role": "assistant", "content": "recent a"},
        {"role": "user", "content": "latest q"},
        {"role": "assistant", "content": "latest a"},
    ]
    compacted = AIBrain._compact_messages(messages, 500)
    # Last 4 messages preserved intact
    assert compacted[-1]["content"] == "latest a"
    assert compacted[-4]["content"] == "recent q"


def test_compact_messages_short_list_unchanged():
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    assert AIBrain._compact_messages(messages, 1000) == messages


# ─── DiscoverResult context_length ────────────────────────────────


def test_discover_result_has_context_length():
    dr = DiscoverResult(available=True, context_length=131072)
    assert dr.context_length == 131072


def test_discover_result_default_context_length():
    dr = DiscoverResult(available=True)
    assert dr.context_length == 0


# ─── Provider context_length property ─────────────────────────────


def test_openai_provider_context_length():
    from core.ai.providers.openai_compat_provider import OpenAICompatibleProvider
    p = OpenAICompatibleProvider("http://localhost:8080/v1", "m", context_length=131072)
    assert p.context_length == 131072


def test_openai_provider_context_length_default():
    from core.ai.providers.openai_compat_provider import OpenAICompatibleProvider
    p = OpenAICompatibleProvider("http://localhost:8080/v1", "m")
    assert p.context_length == 0


def test_ollama_provider_context_length():
    from core.ai.providers.ollama_provider import OllamaProvider
    p = OllamaProvider("http://localhost:11434", "m", context_length=8192)
    assert p.context_length == 8192


def test_anthropic_provider_context_length():
    from core.ai.providers.anthropic_provider import AnthropicProvider
    p = AnthropicProvider(model="claude-sonnet-4-20250514")
    assert p.context_length == 200000


def test_integrated_provider_context_length_default():
    from core.ai.providers.integrated_provider import IntegratedProvider
    p = IntegratedProvider(model="test")
    assert p.context_length == 4096  # default when no tokenizer
