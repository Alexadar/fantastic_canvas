"""Conversation input loop — runs in both Core-only and Core+Server modes.

Supports @tag routing:
  @core <cmd>           — core commands
  @<agent_id> <text>    — send message to agent (bundle's cli_sync)
  @<agent_id> <tool> k=v ... — run a dispatch tool on this agent
"""

import json
import logging
import shlex

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.patch_stdout import patch_stdout

from . import conversation
from .recipients import CoreRecipient, Recipient


def _prompt_text() -> ANSI:
    """Snapchat-style prompt: user-colored bar + `>` cursor."""
    return ANSI(
        f"{conversation.USER_COLOR}{conversation.BAR}{conversation.RESET} "
        f"{conversation.USER_COLOR}>{conversation.RESET} "
    )


logger = logging.getLogger(__name__)


def _parse_value(raw: str):
    """Coerce a CLI arg value: int, float, bool, JSON, or string."""
    if raw == "":
        return ""
    low = raw.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if low in ("null", "none"):
        return None
    # JSON literal (dict / list / quoted string)
    if raw[0] in "{[":
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    # Numeric
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _parse_kv(text: str) -> dict:
    """Parse `key=val key2="quoted val" ...` into a dict. Values coerced."""
    if not text.strip():
        return {}
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    out: dict = {}
    for tok in tokens:
        if "=" not in tok:
            continue
        k, _, v = tok.partition("=")
        k = k.strip()
        if k:
            out[k] = _parse_value(v)
    return out


class InputLoop:
    """Interactive conversation loop with @tag routing."""

    def __init__(self, remote_url: str | None = None, engine=None):
        self._remote_url = remote_url
        self._engine = engine
        self._core = CoreRecipient()
        self._recipients: dict[str, Recipient] = {
            "core": self._core,
        }

    def register_recipient(self, recipient: Recipient) -> None:
        """Register an additional recipient for @tag routing."""
        self._recipients[recipient.name] = recipient

    async def run(self):
        """Main input loop: read → parse → execute → print.

        Uses prompt_toolkit so the input row stays pinned at the bottom of
        the terminal — concurrent `print()` calls from dispatch/agent tasks
        scroll cleanly above the prompt instead of clobbering half-typed input.
        """
        # Show recent conversation only when connecting to running server
        if self._remote_url:
            for entry in conversation.read(max_lines=20):
                print(conversation.format_entry(entry))

        session: PromptSession = PromptSession()
        self._session = session
        with patch_stdout(raw=True):
            while True:
                try:
                    line = await session.prompt_async(_prompt_text())
                    line = line.strip()
                    if not line:
                        continue
                except (EOFError, KeyboardInterrupt):
                    print()
                    break

                if line.lower() in ("exit", "quit", "q"):
                    print()
                    break

                # @tag routing
                if line.startswith("@"):
                    tag, _, rest = line[1:].partition(" ")
                    rest = rest.strip()
                    if tag.lower() in self._recipients:
                        recipient = self._recipients[tag.lower()]
                        await self._dispatch_to(recipient, rest)
                    elif self._engine and self._engine.get_agent(tag):
                        await self._handle_agent_message(tag, rest)
                    else:
                        self._say_system(f"unknown: @{tag}")
                else:
                    # Try as core command; otherwise treat as conversation
                    parsed = self._core.parse(line)
                    if parsed:
                        await self._dispatch_to(self._core, line)
                    else:
                        conversation.say("user", line)
                        if self._remote_url:
                            await self._remote_call(
                                "conversation_say", {"who": "user", "message": line}
                            )

    async def _handle_agent_message(self, agent_id: str, rest: str):
        """Route @{agent_id} input: dispatch tool if first token matches, else cli_sync."""
        from .dispatch import _DISPATCH
        from .tools._plugin_loader import get_bundle_module

        rest = rest.strip()
        head, _, tail = rest.partition(" ")
        head = head.strip()

        # Form A: @{id} <tool_name> key=val ...
        if head and head in _DISPATCH:
            kwargs = _parse_kv(tail)
            kwargs["agent_id"] = agent_id
            try:
                tr = await _DISPATCH[head](**kwargs)
            except Exception as e:
                self._say_system(f"[ERROR] {head}: {e}")
                return
            data = getattr(tr, "data", tr)
            if isinstance(data, dict) and "error" in data:
                self._say_system(f"[ERROR] {data['error']}")
            else:
                print(f"  {head}: {data}")
            # Fire any broadcasts the dispatch produced
            try:
                from .tools import _fire_broadcasts

                if hasattr(tr, "broadcast"):
                    await _fire_broadcasts(tr)
            except Exception:
                pass
            return

        # Form B: @{id} <message> → cli_sync
        if not rest:
            self._say_system(f"@{agent_id}: empty message")
            return

        agent = self._engine.get_agent(agent_id)
        bundle = agent.get("bundle", "") if agent else ""
        mod = get_bundle_module(bundle) if bundle else None
        cli_fn = getattr(mod, "cli_sync", None) if mod else None
        if cli_fn is None:
            self._say_system(f"@{agent_id}: bundle '{bundle}' has no cli_sync")
            return

        entry = conversation.say("user", rest)
        print(conversation.format_entry(entry))
        try:
            reply = await cli_fn(agent_id, rest)
        except Exception as e:
            self._say_system(f"[ERROR] cli_sync: {e}")
            return
        if reply:
            out = conversation.say(agent_id, str(reply))
            print(conversation.format_entry(out))

    def _say_system(self, message: str):
        entry = conversation.say("fantastic", message)
        print(conversation.format_entry(entry))

    async def _run_chat_agent(self, bundle_name: str):
        """Discover and run a bundle's @chat_run function."""
        import importlib.util
        from ._paths import bundled_agents_dir
        from .chat_run import find_chat_run

        tools_file = bundled_agents_dir() / bundle_name / "tools.py"
        if not tools_file.exists():
            self._say_system(f"bundle '{bundle_name}' not found")
            return

        spec = importlib.util.spec_from_file_location(
            f"bundle_{bundle_name}_run",
            str(tools_file),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        run_fn = find_chat_run(mod)
        if run_fn is None:
            self._say_system(f"bundle '{bundle_name}' has no @chat_run function")
            return

        # Reuse the outer loop's prompt session if present, else create one.
        ask_session: PromptSession = getattr(self, "_session", None) or PromptSession()

        async def ask(prompt: str) -> str:
            entry = conversation.say(bundle_name, prompt)
            print(conversation.format_entry(entry))
            answer = await ask_session.prompt_async(_prompt_text())
            answer = answer.strip()
            conversation.say("user", answer)
            return answer

        def say(message: str):
            entry = conversation.say(bundle_name, message)
            print(conversation.format_entry(entry))

        try:
            await run_fn(ask, say)
        except (EOFError, KeyboardInterrupt):
            say("interrupted")
        except Exception as e:
            say(f"error: {e}")

    async def _dispatch_to(self, recipient: Recipient, text: str):
        """Parse and execute via a recipient, or fall through to conversation."""
        parsed = recipient.parse(text)
        if parsed:
            tool_name, args = parsed
            if tool_name == "run_bundle":
                await self._run_chat_agent(args["bundle_name"])
                return
            result = await self._execute(recipient, tool_name, args)
            self._print_result(tool_name, result)
        else:
            # Plain conversation
            conversation.say("user", text)
            if self._remote_url:
                await self._remote_call(
                    "conversation_say", {"who": "user", "message": text}
                )

    async def _execute(self, recipient: Recipient, tool_name: str, args: dict) -> str:
        """Execute a tool — locally via recipient or via REST."""
        if self._remote_url:
            return await self._remote_call(tool_name, args)
        tr = await recipient.execute(tool_name, args)
        if tr is None:
            return f"Unknown command: {tool_name}"
        return self._format_tool_result(tool_name, tr)

    async def _remote_call(self, tool_name: str, args: dict) -> str:
        """Call tool via REST /api/call."""
        import httpx

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._remote_url}/api/call",
                    json={"tool": tool_name, "args": args},
                    timeout=10,
                )
                data = resp.json()
                return data.get("result", str(data))
        except Exception as e:
            return f"[ERROR] {e}"

    def _format_tool_result(self, tool_name: str, tr) -> str:
        """Format a ToolResult for CLI display."""
        data = tr.data
        if isinstance(data, dict) and "error" in data:
            return f"  [ERROR] {data['error']}"
        if tool_name == "list_bundles" and isinstance(data, list):
            lines = []
            for b in data:
                if b.get("instances"):
                    for inst in b["instances"]:
                        display = inst.get("display_name") or inst["id"]
                        children = inst.get("children", 0)
                        lines.append(
                            f"  {b['name']}  {display}  ({inst['id']})  [{children} agents]"
                        )
                else:
                    status = "[available]"
                    lines.append(f"  {b['name']}  {status}")
            return "\n".join(lines) if lines else "  (no bundles found)"
        if tool_name == "conversation_log":
            entries = data.get("entries", [])
            if not entries:
                return "  (no conversation history)"
            return "\n".join(conversation.format_entry(e) for e in entries)
        if isinstance(data, dict):
            # Generic success
            return "  " + " ".join(f"{k}={v}" for k, v in data.items())
        return str(data)

    def _print_result(self, tool_name: str, result: str):
        """Print tool result to CLI."""
        if result:
            print(result)
