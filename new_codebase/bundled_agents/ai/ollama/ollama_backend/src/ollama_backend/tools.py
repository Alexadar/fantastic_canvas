"""ollama bundle — reflect-driven LLM agent with native tool-calling.

The `send` verb does Phase 1 (assemble prompt from real reflect replies,
nothing baked in) + Phase 2 (stream the model with one universal SEND
tool, execute every tool_call via kernel.send, feed reply back via
role:tool with tool_call_id linkage). Loops up to MAX_STEPS.
"""

from __future__ import annotations

import asyncio
import json

_providers: dict = {}
_tasks: dict[str, asyncio.Task] = {}
_locks: dict[str, asyncio.Lock] = {}

# Per-backend cache of "what other agents exist + what they answer".
# Built lazily at assemble time; invalidated automatically after every
# tool_call (which may have mutated the population) and on the
# `refresh_menu` verb (so the LLM can self-invalidate). Never persisted
# to chat.json — it's prepended to the system block on each turn.
_menu_cache: dict[str, list[dict]] = {}


def _invalidate_menu(self_id: str) -> None:
    """Drop the agent menu so the next assemble rebuilds it from live reflect."""
    _menu_cache.pop(self_id, None)


MAX_STEPS = 5
SEND_TIMEOUT = 180.0          # hard ceiling per-generation; releases the lock
DEFAULT_CLIENT_ID = "cli"     # headless / REPL caller defaults here


def _lock_for(self_id: str) -> asyncio.Lock:
    """Per-backend FIFO serializer: only one `_send` runs at a time per
    agent. Concurrent callers (cli, browser tabs) wait their turn."""
    if self_id not in _locks:
        _locks[self_id] = asyncio.Lock()
    return _locks[self_id]

SEND_TOOL = {
    "type": "function",
    "function": {
        "name": "send",
        "description": (
            "Send a message to any agent in the Fantastic substrate. "
            "Universal verb on every agent: reflect (returns identity + state). "
            "Discover agents by sending list_agents to the core agent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {
                    "type": "string",
                    "description": "Agent id to send the payload to (e.g. 'core', 'cli', 'terminal_xxx').",
                },
                "payload": {
                    "type": "object",
                    "description": '{"type": "<verb>", ...fields}. Universal verb: reflect.',
                },
            },
            "required": ["target_id", "payload"],
        },
    },
}


# ─── persistence (routed through file_agent_id) ────────────────


def _safe_client(client_id: str) -> str:
    """Trim and sanitize a client id so it's safe as a filename suffix.
    Spaces / slashes / weirdness collapse to underscores."""
    s = (client_id or DEFAULT_CLIENT_ID).strip() or DEFAULT_CLIENT_ID
    return "".join(c if (c.isalnum() or c in "._-") else "_" for c in s)[:64]


def _chat_path(self_id: str, client_id: str) -> str:
    """Per-client chat thread. Two callers (cli, browser tab) → two files."""
    return f".fantastic/agents/{self_id}/chat_{_safe_client(client_id)}.json"


def _file_agent_id(self_id: str, kernel) -> str | None:
    rec = kernel.get(self_id) or {}
    return rec.get("file_agent_id")


async def _load_history(self_id: str, kernel, client_id: str) -> list[dict]:
    fid = _file_agent_id(self_id, kernel)
    if not fid:
        return []
    r = await kernel.send(fid, {"type": "read", "path": _chat_path(self_id, client_id)})
    if not r or "content" not in r:
        return []
    try:
        return json.loads(r["content"])
    except json.JSONDecodeError:
        return []


async def _save_history(self_id: str, kernel, client_id: str, messages: list[dict]) -> None:
    fid = _file_agent_id(self_id, kernel)
    if not fid:
        return
    await kernel.send(
        fid,
        {
            "type": "write",
            "path": _chat_path(self_id, client_id),
            "content": json.dumps(messages, indent=2),
        },
    )


def _get_provider(id: str, kernel):
    if id not in _providers:
        from ollama_backend.provider import (
            DEFAULT_ENDPOINT,
            DEFAULT_MODEL,
            OllamaProvider,
        )

        rec = kernel.get(id) or {}
        endpoint = rec.get("endpoint", DEFAULT_ENDPOINT)
        model = rec.get("model", DEFAULT_MODEL)
        _providers[id] = OllamaProvider(endpoint=endpoint, model=model)
    return _providers[id]


# ─── prompt assembly (Phase 1) ──────────────────────────────────


def _render_reflect(d: dict) -> str:
    d = dict(d)
    sentence = d.pop("sentence", "")
    fields = "  ".join(
        f"{k}={json.dumps(v) if not isinstance(v, str) else v}" for k, v in d.items()
    )
    return f"{sentence}  {fields}".strip()


async def _build_menu(self_id: str, kernel) -> list[dict]:
    """Reflect on every running agent (skip self) and collect their
    one-line sentence + verb names. Used to grow the system prompt
    into a real "menu of capabilities" the model can see at a glance.
    """
    online = await kernel.send("core", {"type": "list_agents"})
    items: list[dict] = []
    for a in online.get("agents", []):
        if a["id"] == self_id:
            continue   # self is described separately in the prompt
        try:
            r = await kernel.send(a["id"], {"type": "reflect"})
        except Exception:
            r = {}
        verbs = r.get("verbs", {}) if isinstance(r, dict) else {}
        verb_names = list(verbs.keys()) if isinstance(verbs, dict) else list(verbs)
        items.append({
            "id": a["id"],
            "sentence": (r or {}).get("sentence", "") if isinstance(r, dict) else "",
            "verbs": verb_names,
        })
    return items


def _render_menu(menu: list[dict]) -> str:
    """Format the menu as bullet lines for the system prompt."""
    if not menu:
        return "## Available agents\n(none — only `core` and `self`)"
    lines = ["## Available agents (reflect on any for full verb signatures + arg shapes)"]
    for m in menu:
        verbs = m.get("verbs") or []
        head = ", ".join(verbs[:10]) + (" …" if len(verbs) > 10 else "")
        lines.append(f"- `{m['id']}` — {m['sentence']} — verbs: {head or '(none)'}")
    return "\n".join(lines)


_SEND_HOWTO = """## How to use the `send` tool
You have ONE tool: `send(target_id, payload)`. EVERY action goes through it.
- To do something concrete (read a file, run python, list agents, etc.), pick
  an agent from the menu above whose verbs cover what you need, then build
  `{type:'<verb>', ...args}` and pass it as `payload`.
- To learn an agent's full verb signatures (arg names, types):
  `send('<id>', {type:'reflect'})` returns `{verbs: {name: 'doc'}, ...}`.
- To rebuild your menu of agents (useful right after you create one):
  `send('<your_own_id>', {type:'refresh_menu'})` — next turn shows the fresh menu.
- NEVER claim "I don't have access" without trying the menu first. The
  send tool reaches every agent in the system.
"""


async def _assemble(self_id: str, user_text: str, kernel, client_id: str) -> list[dict]:
    primer = await kernel.send("kernel", {"type": "reflect"})
    me = await kernel.send(self_id, {"type": "reflect"})

    # Lazy menu: rebuild only when invalidated (None / missing).
    if self_id not in _menu_cache:
        _menu_cache[self_id] = await _build_menu(self_id, kernel)
    menu = _menu_cache[self_id]

    sys_blocks = [
        _render_reflect(primer),
        f"You are `{self_id}`. " + _render_reflect(me),
        _render_menu(menu),
        _SEND_HOWTO,
    ]
    # System block is rebuilt on EVERY user turn; chat.json holds only
    # the user/assistant turns. Menu + howto are not persisted — they
    # always reflect the latest state at send-time.
    messages: list[dict] = [{"role": "system", "content": "\n\n".join(sys_blocks)}]
    messages.extend(await _load_history(self_id, kernel, client_id))
    messages.append({"role": "user", "content": user_text})
    return messages


# ─── streaming + native tool-calls (Phase 2) ────────────────────


async def _to_caller(kernel, self_id: str, client_id: str, ev: dict) -> None:
    """Route a stream event to the originating caller ONLY.

    - client_id == 'cli': dispatch via `kernel.send` so cli's handler
      runs and prints to stdout (REPL/headless flow).
    - client_id == anything else (browser uuid, etc.): emit on the
      backend's inbox tagged with client_id; the browser's WS
      subscription mirrors it and filters to its own id.

    No fan-out: cli does NOT see browser tokens, and vice versa.
    """
    ev = {**ev, "client_id": client_id}
    if client_id == DEFAULT_CLIENT_ID:
        await kernel.send("cli", ev)
    else:
        await kernel.emit(self_id, ev)


async def _run(self_id: str, user_text: str, kernel, client_id: str) -> dict:
    provider = _get_provider(self_id, kernel)
    messages = await _assemble(self_id, user_text, kernel, client_id)
    last_text = ""

    for _ in range(MAX_STEPS):
        content_parts: list[str] = []
        tool_calls: list[dict] = []
        async for chunk in provider.chat(messages, tools=[SEND_TOOL]):
            if isinstance(chunk, str):
                content_parts.append(chunk)
                await _to_caller(
                    kernel, self_id, client_id,
                    {"type": "token", "text": chunk, "source": self_id},
                )
            else:
                tool_calls.append(chunk["tool_call"])
        last_text = "".join(content_parts)

        if not tool_calls:
            break

        # Record assistant turn carrying its tool_calls.
        # ollama wants `arguments` as a dict (not a JSON string).
        messages.append(
            {
                "role": "assistant",
                "content": last_text,
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": c["arguments"],
                        },
                    }
                    for c in tool_calls
                ],
            }
        )
        # Execute each tool_call; append role:tool reply linked by tool_call_id.
        # Invalidate menu after every tool_call — population may have changed
        # (create_agent / delete_agent), and even unchanged agents may have
        # gained/lost verbs via update. Cheap to rebuild on next user turn.
        for c in tool_calls:
            args = c["arguments"]
            target = args.get("target_id", "")
            payload = args.get("payload", {})
            try:
                reply = await kernel.send(target, payload)
            except Exception as e:
                reply = {"error": str(e)}
            _invalidate_menu(self_id)
            reply_str = json.dumps(reply, default=str)
            await _to_caller(
                kernel, self_id, client_id,
                {
                    "type": "say",
                    "text": f"[tool {target} -> {reply_str[:120]}]",
                    "source": self_id,
                },
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": c["id"],
                    "name": c["name"],
                    "content": reply_str,
                }
            )

    await _to_caller(
        kernel, self_id, client_id, {"type": "done", "source": self_id}
    )

    history = await _load_history(self_id, kernel, client_id)
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": last_text})
    await _save_history(self_id, kernel, client_id, history)
    return {"response": last_text, "final": last_text, "client_id": client_id}


# ─── verbs ──────────────────────────────────────────────────────


async def _reflect(id, payload, kernel):
    """Identity + model + endpoint + generating flag + file_agent_id binding. No args."""
    rec = kernel.get(id) or {}
    from ollama_backend.provider import DEFAULT_ENDPOINT, DEFAULT_MODEL

    return {
        "id": id,
        "sentence": "Ollama-backed LLM agent (native tool-calling).",
        "model": rec.get("model", DEFAULT_MODEL),
        "endpoint": rec.get("endpoint", DEFAULT_ENDPOINT),
        "file_agent_id": rec.get("file_agent_id"),
        "verbs": {n: (f.__doc__ or "").strip().splitlines()[0] for n, f in VERBS.items()},
        "generating": id in _tasks and not _tasks[id].done(),
        "emits": {
            "queued": "{type:'queued', source:<self_id>, client_id} — emitted when send arrives but a previous generation holds the lock. UI marks the message as waiting; first `token` for the same client_id unmarks.",
            "token":  "{type:'token', text:str, source:<self_id>, client_id} — streaming chunk. Routed ONLY to the caller: cli (stdout) when client_id='cli', else this agent's own inbox (browser filters by client_id).",
            "say":    "{type:'say', text:'[tool target -> reply…]', source:<self_id>, client_id} — per tool_call summary. Same routing.",
            "done":   "{type:'done', source:<self_id>, client_id} — end of generation, interrupted, or timed out. Same routing.",
        },
        "concurrency": "Per-backend FIFO lock around `send`: one generation at a time. Other callers wait (and receive a `queued` event so their UI can show it). `reflect`/`history`/`interrupt` skip the lock and stay snappy.",
    }


async def _send(id, payload, kernel):
    """args: text:str (req), client_id:str? (default 'cli'). Streams tokens to ONLY the caller — cli (stdout) for client_id='cli', or the browser tab whose WS is subscribed and filters by client_id otherwise. Persists per-client chat.json. Per-backend FIFO lock: concurrent callers serialize. If the lock is held when this call arrives, emits a `queued` event for the caller so the UI can mark the message; first `token` for the same client_id implicitly unqueues. Returns {response, final, client_id}."""
    if not _file_agent_id(id, kernel):
        return {"error": "ollama_backend: file_agent_id required"}
    text = payload.get("text", "")
    client_id = _safe_client(payload.get("client_id") or DEFAULT_CLIENT_ID)

    lock = _lock_for(id)
    # Best-effort contention detection: if the lock is currently held,
    # tell the caller their request is queued. Race-y vs. taking-it-now
    # but informative — false positives mean a `queued` event arrives
    # right before the first `token`, which the UI handles uniformly
    # (any token unqueues the bubble).
    if lock.locked():
        await _to_caller(kernel, id, client_id, {"type": "queued", "source": id})

    async with lock:
        task = asyncio.create_task(_run(id, text, kernel, client_id))
        _tasks[id] = task
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=SEND_TIMEOUT)
        except asyncio.TimeoutError:
            task.cancel()
            await _to_caller(
                kernel, id, client_id, {"type": "done", "source": id}
            )
            return {"error": f"send: timeout after {SEND_TIMEOUT}s", "client_id": client_id}
        except asyncio.CancelledError:
            await _to_caller(
                kernel, id, client_id, {"type": "done", "source": id}
            )
            return {"response": "", "interrupted": True, "client_id": client_id}
        finally:
            _tasks.pop(id, None)


async def _history(id, payload, kernel):
    """args: client_id:str? (default 'cli'). Returns {messages:[...], client_id} — that client's persisted chat. Failfast if file_agent_id unset."""
    if not _file_agent_id(id, kernel):
        return {"error": "ollama_backend: file_agent_id required"}
    client_id = _safe_client(payload.get("client_id") or DEFAULT_CLIENT_ID)
    return {"messages": await _load_history(id, kernel, client_id), "client_id": client_id}


async def _interrupt(id, payload, kernel):
    """No args. Cancels any in-flight `send` (releases the per-backend lock immediately). Returns {interrupted:bool}."""
    task = _tasks.get(id)
    if task and not task.done():
        task.cancel()
        return {"interrupted": True}
    return {"interrupted": False}


async def _refresh_menu(id, payload, kernel):
    """No args. Drops the cached agent menu so the next user turn rebuilds it from live reflect. Useful right after the LLM creates/deletes/updates an agent. Returns {refreshed:true}."""
    _invalidate_menu(id)
    return {"refreshed": True}


async def _boot(id, payload, kernel):
    """No-op. Returns None."""
    return None


# ─── dispatch ───────────────────────────────────────────────────


VERBS = {
    "reflect": _reflect,
    "send": _send,
    "history": _history,
    "interrupt": _interrupt,
    "refresh_menu": _refresh_menu,
    "boot": _boot,
}


async def handler(id: str, payload: dict, kernel) -> dict | None:
    t = payload.get("type")
    fn = VERBS.get(t)
    if fn is None:
        return {"error": f"ollama: unknown type {t!r}"}
    return await fn(id, payload, kernel)
