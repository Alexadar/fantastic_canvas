"""Message builder with context-budget truncation."""

from __future__ import annotations


SYSTEM_PROMPT = (
    "You are a helpful AI assistant in the Fantastic Canvas environment. "
    "You have access to tools for creating agents, executing code, managing the canvas, "
    "and more. Use tools when the user's request requires taking actions. "
    "IMPORTANT: Never spawn cascades of AI agents — you cannot communicate with them programmatically. "
    "If unsure whether to create agents or run code autonomously, ask the user first. "
    "When creating files, write them to the agent's own folder (.fantastic/agents/{agent_id}/) unless the user specifies a project path. "
    "This keeps the project directory clean."
)


def estimate_tokens(messages: list[dict]) -> int:
    """Rough token count: ~4 chars per token."""
    total = 0
    for m in messages:
        total += len(m.get("content") or "")
        for tc in m.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            total += len(fn.get("name", ""))
            total += len(str(fn.get("arguments", "")))
    return total // 4


def build_messages(
    history: list[dict],
    current_text: str,
    context_length: int = 8192,
    reserve: int = 2048,
    system_prompt: str = SYSTEM_PROMPT,
) -> list[dict]:
    """Build LLM messages with budget-aware history truncation.

    `history`: list of {"role", "text"} (or "content") entries.
    """
    budget = max(1024, context_length - reserve)

    system_msg = {"role": "system", "content": system_prompt}
    user_msg = {"role": "user", "content": current_text}
    used = (len(system_prompt) + len(current_text)) // 4

    # Fill remaining budget with history (newest first)
    history_msgs: list[dict] = []
    for entry in reversed(history):
        role = entry.get("role", "user")
        if role not in ("user", "assistant"):
            continue
        text = entry.get("text") or entry.get("content") or ""
        cost = len(text) // 4
        if used + cost > budget:
            break
        history_msgs.append({"role": role, "content": text})
        used += cost

    return [system_msg] + list(reversed(history_msgs)) + [user_msg]


def compact_messages(messages: list[dict]) -> list[dict]:
    """Truncate older tool results when messages get long."""
    if len(messages) <= 5:
        return messages
    head = messages[:1]
    tail = messages[-4:]
    middle = messages[1:-4]
    compacted = []
    for m in middle:
        if m["role"] == "tool":
            content = m.get("content", "")
            if len(content) > 200:
                compacted.append(
                    {"role": "tool", "content": content[:200] + "...[truncated]"}
                )
            else:
                compacted.append(m)
        elif m["role"] == "assistant" and m.get("tool_calls"):
            text = m.get("content") or ""
            compacted.append(
                {
                    "role": "assistant",
                    "content": text[:100] + "..." if len(text) > 100 else text,
                    "tool_calls": m["tool_calls"],
                }
            )
        else:
            compacted.append(m)
    return head + compacted + tail
