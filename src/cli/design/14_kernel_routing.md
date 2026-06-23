# 14 · Kernel routing (`@<agent> <verb>`)

Status: implemented

Drive any agent in the in-proc **manager kernel** straight from chat. `@<id>
<verb> [k=v…]` sends a command; `@<id>` alone reflects the agent. The reply prints
back into the transcript, sender-tinted. This is the kernel-manager sugar surfaced
as chat.

## Design

```text
   │ you → kernel:  → list_agents kernel              ← activity line (verb + target)
   │ kernel: { "agents": [ { "id": "core" } ] }       ← reply, pretty JSON, kernel-tinted rail
   @kernel ▸ _                                         ← sticky retargets to the agent
```

**Mechanics** (`Route::Kernel` / `Route::Reflect` → `dispatch_kernel`):
- Push a `Tool { verb, target }` activity line `you → <id>` immediately (synchronous
  — always visible even if the send is slow).
- **Live, like `@ai`** — before the send, `kernel.watch(id, CLIENT_ID)` mirrors the
  target's own inbox into our client inbox, so any events it EMITS while handling the
  verb (`token`/`say`/`status`/`done`, or any other activity event — scheduler ticks,
  terminal output, …) render LIVE in the `@<id>` room through the SAME `on_event` path
  the AI turn uses. The brain drives the AI turn lifecycle; a command target just
  renders. Targets that only return a reply emit nothing — their reply still prints.
- Spawn `kernel.send(id, payload)`; the reply is `to_string_pretty`'d and routed
  back via `cmd_tx` as a `<id>: …` message, tinted by `color_for(id)`.
- **k=v coercion** (`parse_kv`): `bool → int → float → JSON literal → string`, so
  `@web reflect depth=2` sends `{type:"reflect", depth:2}` (number, not string).
- Bare `@<id>` → `{type:"reflect"}` (the agent self-describes).
- Aliases: `tree` / `reflect` (no id) reflect the whole kernel id-tree.
- **One render path for all three routes**: `@ai` tokens, `@<id>` command activity,
  and `@sh` PTY output all surface live in their room (the first two share the
  `watch` → `on_event` mirror; `@sh` is the vt100 viewport). No byte/file streams.

**Targets you can reach**: `kernel` (the root/manager), and any agent it has
loaded/spawned (`core`, `web`, `file`, a brain, …) — discoverable via `@kernel
reflect`. Distinct from `@ws` (16), which reaches an *out-of-process* workspace
kernel over HTTP.

## UX

1. **`@kernel list_agents` ⏎** → *expect* a `→ list_agents kernel` activity line,
   then a `{ … "core" … }` reply; prompt retargets to `@kernel ▸`. *feel:* direct,
   addressed, immediate.
2. **`@web reflect depth=2` ⏎** → *expect* the web agent's self-description.
   *feel:* I can inspect any part live.
3. **`@core` (bare) ⏎** → *expect* core's reflect record. *feel:* one keystroke to
   "what is this thing."
4. **Next bare line** → *expect* it reuses `@kernel` (sticky). *feel:* I don't
   re-address every command.

## Drive

```script
wait 2500
key space
wait 600
type @kernel list_agents
key enter
wait 2500
shot kernel_reply
```

## Judge

- **Activity + reply** — PASS if both the `→ list_agents kernel` line and a `core`
  reply render (railed, kernel-tinted).
- **Retarget** — PASS if the prompt becomes `@kernel ▸` after the send.
- **k=v coercion** — PASS if a numeric arg arrives as a number (inspect a
  `reflect depth=2` reply / trust the unit tests in `chat.rs`).
- **Bottom-anchored** — PASS if the reply sits just above the input.
- **Overall** — PASS if driving the kernel feels like talking to it, not a CLI.
