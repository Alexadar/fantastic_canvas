"""Agentic loop — streams provider output, executes tool calls, feeds back."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from core.dispatch import _TOOL_DISPATCH

from .messages import estimate_tokens, compact_messages
from .provider_protocol import GenerationResult

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 20


async def run_agentic_loop(
    agent_id: str,
    bundle: str,
    provider: Any,
    messages: list[dict],
    tools: list[dict],
    broadcast: Callable,
    abort_flag: dict,
) -> str:
    """Run provider.generate_with_tools in a tool-calling loop.

    Streams `{bundle}_response` broadcasts (text chunks, done flags).
    Sends `{bundle}_state` broadcasts for state transitions.
    Sends `{bundle}_error` on failure.
    Returns the accumulated assistant text.

    DOES NOT save to chat.json — caller is responsible via `{bundle}_save_message`.
    """
    await broadcast(
        {"type": f"{bundle}_state", "agent_id": agent_id, "state": "thinking"}
    )

    full_response = ""
    in_think = False
    ctx_len = getattr(provider, "context_length", 0) or 8192
    budget = max(1024, ctx_len - 2048)

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            if abort_flag.get(agent_id):
                abort_flag[agent_id] = False
                break

            # Compact if over budget
            if estimate_tokens(messages) > budget * 0.9:
                messages = compact_messages(messages)

            result: GenerationResult | None = None
            async for token in provider.generate_with_tools(messages, tools):
                if abort_flag.get(agent_id):
                    abort_flag[agent_id] = False
                    break
                if isinstance(token, GenerationResult):
                    result = token
                else:
                    if "<think>" in token:
                        in_think = True
                        continue
                    if "</think>" in token:
                        in_think = False
                        await broadcast(
                            {
                                "type": f"{bundle}_state",
                                "agent_id": agent_id,
                                "state": "responding",
                            }
                        )
                        continue
                    if in_think:
                        continue
                    full_response += token
                    await broadcast(
                        {
                            "type": f"{bundle}_response",
                            "agent_id": agent_id,
                            "text": token,
                            "done": False,
                        }
                    )

            if result is None or not result.tool_calls:
                break

            # Append assistant turn with tool_calls
            messages.append(
                {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        }
                        for tc in result.tool_calls
                    ],
                }
            )

            # Execute each tool call, append results
            for tc in result.tool_calls:
                tool_result = await _execute_tool(tc["name"], tc["arguments"])
                messages.append({"role": "tool", "content": tool_result})
                await broadcast(
                    {
                        "type": f"{bundle}_response",
                        "agent_id": agent_id,
                        "text": f"\n[tool: {tc['name']}]\n",
                        "done": False,
                    }
                )
    except Exception as exc:
        logger.exception("AI loop error for agent=%s", agent_id)
        await broadcast(
            {
                "type": f"{bundle}_error",
                "agent_id": agent_id,
                "error": str(exc),
            }
        )

    # Final done signal
    await broadcast(
        {
            "type": f"{bundle}_response",
            "agent_id": agent_id,
            "text": full_response,
            "done": True,
        }
    )
    await broadcast({"type": f"{bundle}_state", "agent_id": agent_id, "state": "idle"})

    return full_response


async def _execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name, return JSON-stringified result."""
    fn = _TOOL_DISPATCH.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        if isinstance(arguments, str):
            arguments = json.loads(arguments) if arguments else {}
        result = await fn(**(arguments or {}))
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)
        return str(result)
    except Exception as e:
        return json.dumps({"error": f"Tool {name} failed: {e}"})
