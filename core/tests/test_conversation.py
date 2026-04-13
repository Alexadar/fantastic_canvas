"""Tests for core.conversation — ring buffer + Snapchat-style formatting."""

from core.conversation import (
    say,
    read,
    clear,
    format_entry,
    actor_color,
    CONVERSATION_BUFFER_SIZE,
    CORE_COLOR,
    USER_COLOR,
    AGENT_COLOR,
    AI_COLOR,
    BAR,
    BOLD,
    RESET,
    CORE_ACTORS,
    _buffer,
)


def setup_function():
    """Clear buffer before each test."""
    clear()


def test_say():
    entry = say("user", "hello")
    assert entry["who"] == "user"
    assert entry["message"] == "hello"
    assert "ts" in entry


def test_read():
    say("user", "one")
    say("system", "two")
    entries = read()
    assert len(entries) == 2
    assert entries[0]["message"] == "one"
    assert entries[1]["message"] == "two"


def test_read_max_lines():
    for i in range(10):
        say("user", f"msg{i}")
    entries = read(max_lines=3)
    assert len(entries) == 3
    assert entries[0]["message"] == "msg7"
    assert entries[2]["message"] == "msg9"


def test_eviction():
    for i in range(CONVERSATION_BUFFER_SIZE + 50):
        say("user", f"msg{i}")
    assert len(_buffer) == CONVERSATION_BUFFER_SIZE
    entries = read(max_lines=CONVERSATION_BUFFER_SIZE)
    assert entries[0]["message"] == "msg50"


def test_clear():
    say("user", "hello")
    assert len(read()) == 1
    clear()
    assert len(read()) == 0


def test_format_entry_structure_core_color():
    """Block layout: \\n{color+bold}{who}{reset}\\n\\n{color}█{reset} body\\n"""
    entry = say("fantastic", "started")
    formatted = format_entry(entry)
    expected = (
        f"\n{CORE_COLOR}{BOLD}fantastic{RESET}\n\n{CORE_COLOR}{BAR}{RESET} started\n"
    )
    assert formatted == expected


def test_format_entry_user_color():
    entry = say("user", "hello")
    formatted = format_entry(entry)
    expected = f"\n{USER_COLOR}{BOLD}user{RESET}\n\n{USER_COLOR}{BAR}{RESET} hello\n"
    assert formatted == expected


def test_format_entry_agent_color():
    entry = say("actor_a", "registered")
    formatted = format_entry(entry)
    expected = (
        f"\n{AGENT_COLOR}{BOLD}actor_a{RESET}\n\n{AGENT_COLOR}{BAR}{RESET} registered\n"
    )
    assert formatted == expected


def test_format_entry_bar_color_matches_actor_color():
    """Each actor category colors BOTH the name AND the bar with its own color."""
    cases = [
        ("fantastic", CORE_COLOR),
        ("system", CORE_COLOR),
        ("user", USER_COLOR),
        ("ai", AI_COLOR),
        ("ollama_abc123", AGENT_COLOR),
        ("some_bundle", AGENT_COLOR),
    ]
    for who, expected in cases:
        clear()
        entry = say(who, "msg")
        formatted = format_entry(entry)
        # The bar is tinted with the actor color.
        assert f"{expected}{BAR}{RESET}" in formatted, (who, formatted)
        # Name header uses the same color.
        assert f"{expected}{BOLD}{who}{RESET}" in formatted, (who, formatted)
        # No other color appears on the bar.
        for other in {CORE_COLOR, USER_COLOR, AGENT_COLOR, AI_COLOR} - {expected}:
            assert f"{other}{BAR}" not in formatted, (who, other, formatted)


def test_format_entry_multiline_body():
    """Each line of the body gets its own bar prefix."""
    entry = say("user", "line one\nline two")
    formatted = format_entry(entry)
    assert f"{USER_COLOR}{BAR}{RESET} line one" in formatted
    assert f"{USER_COLOR}{BAR}{RESET} line two" in formatted
    # Header appears exactly once
    assert formatted.count(f"{BOLD}user{RESET}") == 1


def test_format_entry_empty_message():
    entry = say("user", "")
    formatted = format_entry(entry)
    # Still emits the block; body is a single empty line behind a bar.
    assert f"{BOLD}user{RESET}" in formatted
    assert f"{USER_COLOR}{BAR}{RESET} " in formatted


def test_actor_color_categories():
    for actor in CORE_ACTORS:
        assert actor_color(actor) == CORE_COLOR
    assert actor_color("user") == USER_COLOR
    assert actor_color("User") == USER_COLOR
    assert actor_color("actor_a") == AGENT_COLOR
    assert actor_color("actor_b") == AGENT_COLOR
    assert actor_color("mybundle") == AGENT_COLOR
