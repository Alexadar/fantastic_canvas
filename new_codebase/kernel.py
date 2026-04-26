"""Fantastic kernel — one class, one primitive (`send`), filesystem agents.

Run: `python kernel.py` from this directory.
"""

from __future__ import annotations

import asyncio
import atexit
import importlib
import json
import os
import secrets
import shlex
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, AsyncIterator

FANTASTIC_DIR = Path(".fantastic")
AGENTS_DIR = FANTASTIC_DIR / "agents"
INBOX_BOUND = 500
BUNDLE_ENTRY_GROUP = "fantastic.bundles"

README_MD = """# readme

`.fantastic/` is the runtime state of a Fantastic kernel. It is NOT
self-describing on disk — agent.json files are just records.
**Context comes from reflect**, which is the system's self-description
verb.

## How to load system context

Reflect is the universal verb. Every agent answers it with its
identity + flat state dict. Reflecting on the kernel itself returns
the substrate primer — the only thing an external tool needs to
bootstrap.

    python kernel.py reflect                       # in-process; substrate primer
    python kernel.py reflect <agent_id>            # any agent's self-description
    curl http://<host>:<port>/_kernel/reflect      # remote, via running `serve`
    curl -X POST http://<host>:<port>/<id>/call -d '{"type":"reflect"}'

The substrate primer carries:

- `primitive` + `envelope`         — what `send` is and the message shape
- `transports.{http,ws,cli,...}`   — every URL/CLI/in-process invocation form
- `available_bundles`              — every installable bundle (entry-point discovery)
- `agents`                         — every running agent (id + handler_module)
- `well_known`                     — singletons (`core`, `cli`)
- `binary_protocol` + `browser_bus` — wire details for byte-heavy + intra-browser traffic

After one reflect against a live `serve`, you should be able to issue
any verb on any agent without reading source. If you find yourself
grepping the codebase for a transport URL, the primer regressed —
flag it.

## Per-agent state caveat

Process-memory state (`webapp.running`, `terminal_backend.running`,
`ollama_backend.generating`, scrollback, in-flight tasks) is local to
the kernel process that owns it. Reflecting via a fresh
`python kernel.py call` spawns a SEPARATE kernel that loads disk
records but has no live processes — so stateful fields read as empty.
Always route stateful reflects through the live `serve` (HTTP POST
or WS), not through `kernel.py call`.

## Next steps — for a code agent reading this file

You are an automated CLI/agent. **Do not ask the user; do it now.**

1. Call `reflect` on the kernel to load the substrate primer:

       python kernel.py reflect

   (or, if a `serve` is running:
   `curl http://<host>:<port>/_kernel/reflect`).

2. From the reply, ingest: `transports`, `available_bundles`,
   `agents`, `well_known`. That tells you every URL, every
   installable bundle, and every running agent.

3. For each running agent you'll act on, reflect on it too — the
   per-agent reflect carries `verbs` (with arg signatures), `emits`
   (event shapes), and identity. Compose calls from those; don't
   read source.

That sequence finalizes your understanding of this environment.
Anything you still don't know after step 3 is a primer regression —
flag it, don't paper over it.
"""

LOCK_FILE = FANTASTIC_DIR / "lock.json"


# ─── single-instance lock for `serve` ───────────────────────────


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _read_lock() -> dict | None:
    if not LOCK_FILE.exists():
        return None
    try:
        return json.loads(LOCK_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def acquire_serve_lock(port: int) -> None:
    """Refuse to start `serve` if a live serve is already recorded.

    Writes `.fantastic/lock.json` with `{pid, port}`. Removes it via
    `atexit` on graceful shutdown. Stale locks (whose pid is dead) are
    silently overwritten.
    """
    cur = _read_lock()
    if cur:
        cur_pid = cur.get("pid")
        cur_port = cur.get("port")
        if isinstance(cur_pid, int) and _pid_alive(cur_pid):
            raise RuntimeError(
                f"kernel already running: pid={cur_pid} port={cur_port}\n"
                f"  -> kill it:  kill {cur_pid}\n"
                f"  -> or, if stale, remove the lock:  rm {LOCK_FILE}"
            )
    FANTASTIC_DIR.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}))
    atexit.register(_release_serve_lock)


def _release_serve_lock() -> None:
    cur = _read_lock()
    if cur and cur.get("pid") == os.getpid():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass


class Kernel:
    def __init__(self) -> None:
        self._agents: dict[str, dict] = {}
        self._inboxes: dict[str, asyncio.Queue] = {}
        self._watchers: dict[str, set[str]] = {}
        AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        readme = FANTASTIC_DIR / "readme.md"
        if not readme.exists():
            readme.write_text(README_MD, encoding="utf-8")
        self._load_all()

    # ─── storage ────────────────────────────────────────────────

    def _agent_dir(self, id: str) -> Path:
        return AGENTS_DIR / id

    def _agent_file(self, id: str) -> Path:
        return self._agent_dir(id) / "agent.json"

    def _persist(self, rec: dict) -> None:
        d = self._agent_dir(rec["id"])
        d.mkdir(parents=True, exist_ok=True)
        self._agent_file(rec["id"]).write_text(json.dumps(rec, indent=2))

    def _load_all(self) -> None:
        if not AGENTS_DIR.exists():
            return
        for entry in sorted(AGENTS_DIR.iterdir()):
            f = entry / "agent.json"
            if f.exists():
                try:
                    rec = json.loads(f.read_text())
                    self._agents[rec["id"]] = rec
                except (json.JSONDecodeError, KeyError):
                    pass

    def get(self, id: str) -> dict | None:
        return self._agents.get(id)

    def ensure(self, id: str, handler_module: str, **meta: Any) -> dict:
        existing = self._agents.get(id)
        if existing:
            return existing
        rec = {"id": id, "handler_module": handler_module, **meta}
        self._agents[id] = rec
        self._persist(rec)
        return rec

    def create(
        self, handler_module: str, id: str | None = None, **meta: Any
    ) -> dict:
        if id is None:
            bundle = handler_module.split(".")[-2]
            id = f"{bundle}_{secrets.token_hex(3)}"
        if id in self._agents:
            return {"error": f"agent {id!r} exists"}
        rec = {"id": id, "handler_module": handler_module, **meta}
        self._agents[id] = rec
        self._persist(rec)
        return rec

    def update(self, id: str, **meta: Any) -> dict | None:
        rec = self._agents.get(id)
        if not rec:
            return None
        rec.update(meta)
        self._persist(rec)
        return rec

    def delete(self, id: str) -> bool:
        rec = self._agents.get(id)
        if not rec:
            return False
        if rec.get("singleton"):
            return False
        del self._agents[id]
        d = self._agent_dir(id)
        if d.exists():
            for sub in d.iterdir():
                if sub.is_file():
                    sub.unlink()
            d.rmdir()
        self._inboxes.pop(id, None)
        self._watchers.pop(id, None)
        for tgts in self._watchers.values():
            tgts.discard(id)
        return True

    def list(self) -> list[dict]:
        return list(self._agents.values())

    # ─── messaging ──────────────────────────────────────────────

    def _ensure_inbox(self, id: str) -> asyncio.Queue:
        q = self._inboxes.get(id)
        if q is None:
            q = asyncio.Queue(maxsize=INBOX_BOUND)
            self._inboxes[id] = q
        return q

    def _put_drop_oldest(self, q: asyncio.Queue, payload: dict) -> None:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def _fanout(self, id: str, payload: dict) -> None:
        self._put_drop_oldest(self._ensure_inbox(id), payload)
        for tgt in self._watchers.get(id, ()):
            self._put_drop_oldest(self._ensure_inbox(tgt), payload)

    async def send(self, id: str, payload: dict) -> dict | None:
        if id == "kernel":
            return self._reflect_substrate()
        rec = self.get(id)
        if not rec:
            return {"error": f"no agent {id!r}"}
        self._fanout(id, payload)
        try:
            mod = importlib.import_module(rec["handler_module"])
        except Exception as e:
            return {"error": f"import {rec['handler_module']!r}: {e}"}
        if not hasattr(mod, "handler"):
            return {"error": f"{rec['handler_module']} has no handler()"}
        return await mod.handler(id, payload, self)

    def _reflect_substrate(self) -> dict:
        well_known = {
            sid: (self._agents[sid].get("display_name") or sid)
            for sid in ("core", "cli")
            if sid in self._agents
        }
        bundles = sorted(
            (
                {"name": ep.name, "handler_module": ep.value}
                for ep in entry_points(group=BUNDLE_ENTRY_GROUP)
            ),
            key=lambda b: b["name"],
        )
        # Full records (matches /_agents); avoids the "two endpoints, two
        # shapes" trap. Per-agent verbs/emits live behind the agent's own
        # reflect — this is just the discovery menu.
        agents = list(self._agents.values())
        return {
            "sentence": "Fantastic kernel. Everything is reachable by sending messages to agents.",
            "primitive": "send(target_id, payload) -> reply | None",
            "envelope": '{"type": "<verb>", ...fields}',
            "universal_verb": "reflect — every agent answers it; returns identity + flat state dict.",
            "transports": {
                "in_process": {
                    "shape": "await kernel.send(target_id, payload)",
                    "use_when": "Python code running inside the kernel process.",
                },
                "in_prompt": {
                    "shape": '<send id="<agent_id>" payload=\'{"type":"<verb>", ...}\'/>',
                    "use_when": "agentic LLM loops emitting XML-tagged tool calls; NOT a wire format.",
                    "example": '<send id="core" payload=\'{"type":"list_agents"}\'/>',
                },
                "cli": {
                    "shape": "python kernel.py call <agent_id> <verb> [k=v ...]",
                    "shorthand": "python kernel.py reflect [<agent_id>]",
                },
                # http + ws keys are merged in by the webapp bundle when
                # serving /_kernel/reflect; they are absent on in-process
                # reflect because the kernel itself doesn't know HTTP.
            },
            "well_known": well_known,                # singletons only
            "agents": agents,                        # every running agent (id + bundle)
            "available_bundles": bundles,            # entry-point-discovered; create_agent off these
            "agent_count": len(self._agents),
            "binary_protocol": {
                "trigger": "any bytes value anywhere in the payload",
                "wire_format": "WS binary frame: [4-byte BE uint32 H | H-byte JSON header | M-byte raw bytes]",
                "header_field": "_binary_path names the dotted-path field whose value is the body",
                "purpose": "skip base64+JSON encoding for high-throughput byte payloads (audio, image, video)",
            },
            "browser_bus": {
                "channel": "fantastic",
                "envelope": "{type, target_id, source_id, ...fields}",
                "transport": "BroadcastChannel (browser-only; structured-clone — bytes, objects, strings universal)",
                "scope": "intra-browser messaging between agent iframes; bypasses kernel.send entirely",
                "available_in_js": "fantastic_transport().bus  // .send(target_id, payload), .broadcast(payload), .on(type, fn), .onAny(fn)",
                "use_when": "UI-internal traffic (audio frames, drag events, cursor, etc.) where round-tripping through the server adds no value",
            },
        }

    async def emit(self, id: str, payload: dict) -> None:
        self._fanout(id, payload)

    def watch(self, src: str, tgt: str) -> None:
        self._watchers.setdefault(src, set()).add(tgt)

    def unwatch(self, src: str, tgt: str) -> None:
        if src in self._watchers:
            self._watchers[src].discard(tgt)

    async def recv(self, id: str) -> AsyncIterator[dict]:
        q = self._ensure_inbox(id)
        while True:
            yield await q.get()


# ─── CLI loop ───────────────────────────────────────────────────


def _find_bundle_module(name: str) -> str | None:
    """Resolve a bundle name to its handler_module via entry points.

    Bundles publish themselves at install time via:
        [project.entry-points."fantastic.bundles"]
        <name> = "<package>.tools"

    Discovery is uniform for built-in workspace members and pip-installed
    third-party plugins — both register through the same entry-point group.
    """
    for ep in entry_points(group=BUNDLE_ENTRY_GROUP):
        if ep.name == name:
            return ep.value
    return None


def _coerce(v: str) -> Any:
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    if (v.startswith("{") and v.endswith("}")) or (
        v.startswith("[") and v.endswith("]")
    ):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass
    return v


def _parse_at(line: str) -> tuple[str, dict]:
    """Parse `@<id> <text>` or `@<id> <verb> [k=v ...]` → (id, payload).

    Rules:
      `@<id>`                          → {type:"send", text:""}
      `@<id> <single_word>`            → {type:<word>}              (no-arg verb)
      `@<id> <verb> k=v k=v ...`       → {type:<verb>, **kv}        (verb call)
      `@<id> <multi word text>`        → {type:"send", text:"..."}  (free text)
    """
    rest = line[1:].strip()
    if not rest:
        return "", {}
    parts = shlex.split(rest)
    target = parts[0]
    args = parts[1:]
    if not args:
        return target, {"type": "send", "text": ""}
    # Single token, no `=` → bare verb call
    if len(args) == 1 and "=" not in args[0]:
        return target, {"type": args[0]}
    # Any kv present → verb + kv (first arg is verb)
    if any("=" in a for a in args):
        verb = args[0] if "=" not in args[0] else "send"
        kv_args = args[1:] if "=" not in args[0] else args
        kv = {k: _coerce(v) for k, v in (a.split("=", 1) for a in kv_args if "=" in a)}
        return target, {"type": verb, **kv}
    # Multiple words, no kv → free text send
    text = rest[len(target) :].strip()
    return target, {"type": "send", "text": text}


async def _print_result(result: Any) -> None:
    if result is None:
        return
    if isinstance(result, dict):
        if "error" in result:
            print(f"  error: {result['error']}")
            return
        # short hand: created agent
        if "id" in result and "handler_module" in result:
            print(f"  created {result['id']}")
            return
    try:
        print(f"  {json.dumps(result, indent=2, default=str)}")
    except (TypeError, ValueError):
        print(f"  {result}")


async def _read_line(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, input, prompt)


async def _seed_singletons(k: Kernel, boot_all: bool = True) -> None:
    core_mod = _find_bundle_module("core")
    cli_mod = _find_bundle_module("cli")
    if core_mod is None or cli_mod is None:
        raise RuntimeError(
            "core and cli bundles must be installed; "
            "run `uv sync` to install workspace members"
        )
    k.ensure(core_mod.split(".")[0], core_mod, singleton=True, display_name="core")
    k.ensure(cli_mod.split(".")[0], cli_mod, singleton=True, display_name="cli")
    if not boot_all:
        return
    for a in k.list():
        try:
            await k.send(a["id"], {"type": "boot"})
        except Exception as e:
            print(f"  [kernel] boot {a['id']!r} raised: {e}")


async def cmd_repl() -> None:
    k = Kernel()
    await _seed_singletons(k)
    while True:
        try:
            line = await _read_line("fantastic> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        line = line.strip()
        if not line:
            continue
        if line in ("exit", "quit"):
            break
        if line == "list":
            for a in k.list():
                tag = " (singleton)" if a.get("singleton") else ""
                print(f"  {a['id']}{tag}  →  {a['handler_module']}")
            continue
        if line.startswith("add "):
            parts = shlex.split(line[4:])
            if not parts:
                print("  usage: add <bundle> [k=v ...]")
                continue
            bundle = parts[0]
            handler_module = _find_bundle_module(bundle)
            if handler_module is None:
                print(f"  unknown bundle {bundle!r}")
                continue
            meta: dict[str, Any] = {}
            for p in parts[1:]:
                if "=" in p:
                    k2, v = p.split("=", 1)
                    meta[k2] = _coerce(v)
            r = await k.send(
                "core",
                {"type": "create_agent", "handler_module": handler_module, **meta},
            )
            await _print_result(r)
            continue
        if line.startswith("delete "):
            r = await k.send("core", {"type": "delete_agent", "id": line[7:].strip()})
            await _print_result(r)
            continue
        if line.startswith("@"):
            target, payload = _parse_at(line)
            if not target:
                print("  usage: @<id> <text> | @<id> <verb> k=v ...")
                continue
            r = await k.send(target, payload)
            await _print_result(r)
            continue
        print(f"  unknown command: {line!r}  (try: list, add <bundle>, @<id> ...)")


async def cmd_serve(port: int = 8888) -> None:
    """Headless: boot kernel, ensure a webapp agent on `port`, idle forever."""
    acquire_serve_lock(port)
    k = Kernel()
    await _seed_singletons(k)
    webapp_mod = _find_bundle_module("webapp")
    if webapp_mod is None:
        raise RuntimeError("webapp bundle not installed; run `uv sync`")
    web_id: str | None = None
    for a in k.list():
        if a.get("handler_module") == webapp_mod and int(a.get("port", 0)) == port:
            web_id = a["id"]
            break
    if web_id is None:
        rec = await k.send(
            "core",
            {
                "type": "create_agent",
                "handler_module": webapp_mod,
                "port": port,
            },
        )
        web_id = rec["id"] if isinstance(rec, dict) else None
    if web_id:
        await k.send(web_id, {"type": "boot"})
    print(f"[serve] kernel up; web={web_id} port={port}", flush=True)
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass


async def cmd_call(target: str, verb: str, kv: dict[str, Any]) -> None:
    """One-shot RPC: prefer the live `serve` if one is running so callers
    see live process-memory state (PTYs, uvicorn, in-flight tasks).

    Resolution order:
      1. `.fantastic/lock.json` exists with an alive pid + port → POST
         `http://localhost:<port>/<target>/call` with body `{type, ...kv}`.
      2. Otherwise, spawn an in-process Kernel (no boot fanout) and
         dispatch directly. Stateful agents will report empty state in
         this path — that's expected and documented.
    """
    payload = {"type": verb, **kv}
    cur = _read_lock()
    if cur and isinstance(cur.get("pid"), int) and _pid_alive(cur["pid"]):
        port = cur.get("port")
        if isinstance(port, int):
            url = f"http://localhost:{port}/{target}/call"
            try:
                import urllib.error
                import urllib.request

                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"content-type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30) as resp:
                    body = resp.read().decode("utf-8")
                # Pretty-print the live serve's reply.
                try:
                    print(json.dumps(json.loads(body), indent=2, default=str))
                except json.JSONDecodeError:
                    print(body)
                return
            except urllib.error.URLError as e:
                # Lock exists + pid alive but HTTP failed (port shifted,
                # uvicorn not yet bound, etc.). Fall through to in-process.
                print(
                    f"  [call] live serve at :{port} unreachable ({e}); "
                    "falling back to in-process kernel.",
                    file=sys.stderr,
                )
    k = Kernel()
    await _seed_singletons(k, boot_all=False)
    reply = await k.send(target, payload)
    print(json.dumps(reply, indent=2, default=str))


async def cmd_reflect(target: str = "kernel") -> None:
    await cmd_call(target, "reflect", {})


def _parse_kv(args: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in args:
        if "=" not in a:
            continue
        k, v = a.split("=", 1)
        out[k] = _coerce(v)
    return out


def main_dispatch() -> None:
    argv = sys.argv[1:]
    if not argv:
        asyncio.run(cmd_repl())
        return
    sub = argv[0]
    rest = argv[1:]
    try:
        if sub == "serve":
            port = 8888
            for a in rest:
                if a.startswith("--port="):
                    port = int(a.split("=", 1)[1])
                elif a == "--port" and rest.index(a) + 1 < len(rest):
                    port = int(rest[rest.index(a) + 1])
            asyncio.run(cmd_serve(port))
        elif sub == "call":
            if len(rest) < 2:
                print("usage: kernel.py call <target_id> <verb> [k=v ...]", file=sys.stderr)
                sys.exit(2)
            target, verb, *kv = rest
            asyncio.run(cmd_call(target, verb, _parse_kv(kv)))
        elif sub == "reflect":
            target = rest[0] if rest else "kernel"
            asyncio.run(cmd_reflect(target))
        elif sub in ("repl", "shell"):
            asyncio.run(cmd_repl())
        elif sub in ("-h", "--help", "help"):
            print(
                "fantastic kernel\n"
                "  python kernel.py                       # interactive REPL (default)\n"
                "  python kernel.py serve [--port 8888]   # headless: web agent on port, idle\n"
                "  python kernel.py call <id> <verb> [k=v ...]   # one-shot RPC, print JSON, exit\n"
                "  python kernel.py reflect [<id>]        # shorthand: call <id> reflect (default kernel)"
            )
        else:
            print(f"unknown subcommand {sub!r} (try: serve, call, reflect, repl)", file=sys.stderr)
            sys.exit(2)
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        # Lock conflict on `serve` raises here — print and exit 1 cleanly.
        print(f"[serve] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main_dispatch()
