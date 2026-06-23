# 16 · Workspace kernel (`@ws`)

Status: implemented · live-gated (spawns a real process)

The **manager substance**: `@ws` reaches a *sovereign, out-of-process* kernel for
the current directory — **any runtime** (rust/python/swift), attach-by-default,
spawn-as-fallback. This is where multi-runtime actually lives; the in-proc manager
(14) drives it over loopback HTTP through the same `send` shape.

## Design

```text
   host: 1 agents · ws: rust ▸ http://127.0.0.1:PORT · @ai · @sh · @ws · …   ← status reflects ws
   │ you → ws:  → up rust
   │ ws: spawned · core · http://127.0.0.1:54321         ← attached vs spawned + base_url
   │ you → ws:  → list_agents
   │ ws: { "agents": [ { "id": "core" }, … ] }            ← driven over HTTP
   @ws ▸ _
```

**Mechanics** (`Route::Workspace` → `dispatch_workspace`; `fantastic_host::gateway`):
- `@ws up [rust|python|swift]` → `Workspace{dir:cwd}.attach_or_spawn(rt)`:
  **attach** an already-running kernel (read `.fantastic/lock.json` + the bound web
  port, liveness = HTTP `reflect`-ping — never `kill(pid,0)`); else **spawn** the
  libs' `fantastic_kernel` binary detached in cwd, seed the serve surface
  (store→web→web_ws/web_rest), wait for the lock + a reflect-ping.
- `@ws <verb> [k=v…]` → `POST /<rest>/kernel` `{type:verb,…}` to the workspace
  **ROOT**; bare `@ws` → reflect its id-tree. `@ws down` → graceful stop.
- Async lifecycle/verbs run in spawned tasks holding a cloned `KernelHandle`
  (a `reqwest::Client`), reporting back via `ws_tx` → `handle_ws_event`. `ws_busy`
  guards overlapping lifecycle ops. A **stale lock** is surfaced as a choice,
  never auto-killed.
- Headless twins of all this are the `up` / `k` / `down` subcommands (18).

**Why out-of-process**: embedding every runtime in the Rust app would defeat the
multi-runtime kernel. The manager spawns/attaches per-dir kernels of *any* runtime
and talks to them over one transport (loopback HTTP/WS; remote later = `ssh -L`).

## UX

1. **`@ws up` in a fresh dir** → *expect* `spawned · core · <url>`; status shows
   `ws: rust`. *feel:* I conjured a kernel for this folder.
2. **`@ws up` again (or another window)** → *expect* `attached · …` (same kernel,
   no second process). *feel:* it found the running one.
3. **`@ws list_agents`** → *expect* the workspace's agents over HTTP. *feel:* same
   chat, now driving a different (remote-ish) kernel.
4. **`@ws up python`** → *expect* a python-runtime kernel. *feel:* multi-runtime,
   same UX.
5. **`@ws down`** → *expect* graceful shutdown, status back to `ws: none`. *feel:*
   clean teardown.

## Drive (live-gated — spawns a process)

```text
# Not in the default headful suite (spawns a real kernel + binds a port).
# Mirror of gateway tests/gateway_live.rs (#[ignore]). To exercise by hand:
#   wait 2500 ; key space ; wait 600
#   type @ws up
#   key enter ; wait 4000 ; shot ws_up         # expect spawned/attached + url
#   type @ws list_agents
#   key enter ; wait 2000 ; shot ws_agents      # expect agents over HTTP
#   type @ws down ; key enter ; wait 1500 ; shot ws_down
```

## Judge

- **Attach-or-spawn** — PASS if first `up` spawns and a second `up` attaches the
  same kernel (no duplicate process); liveness via reflect-ping.
- **Over-the-wire verbs** — PASS if `@ws list_agents` returns the workspace tree.
- **Runtime choice** — PASS if `@ws up python` yields a python kernel.
- **Status truth** — PASS if the status line reflects ws state + base_url.
- **Stale lock** — PASS if a stale lock is surfaced as a choice, not silently
  killed.
- **Overall** — PASS if a per-dir, any-runtime kernel feels one line away.
