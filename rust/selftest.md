# Fantastic selftests (Rust)

Every crate owns a hand-written, executable test spec. AI agents
(Claude Code, etc.) read these files, ask required pre-flight questions,
drive the system at the user-facing surface, and fill summary tables.

Complement to `cargo test` — `cargo test` covers in-process unit logic;
selftests cover the user surface (CLI, HTTP, WS, browser).

## For Claude Code / other AI agents

1. Read this index completely.
2. Parse user intent → set of scopes to **INCLUDE / EXCLUDE**.
3. From the index table, pick files whose scopes are all allowed.
4. For each selected file, in order:
   - Read it end-to-end.
   - If `requires:` lists pre-flight items, **ASK USER** for missing
     info (running daemon, free port, etc.) **BEFORE** wiping any state.
   - Run tests in numerical order.
   - Capture pass/fail + notes per test.
5. After all files: emit ONE aggregate report — rows (file, test#),
   columns (name, pass/fail, notes). List skipped files with reason.

Strict rules:

- Never silently fake a skip.
- Never run destructive ops without user confirmation if state exists.
- If a regression signal in a test triggers, **STOP** that file's
  remaining tests and flag it.
- Do not invent expected output — ask if the spec is unclear.
- A correctly-deployed `fantastic` answers `kernel.reflect` over WS
  with every URL/transport/bundle/agent you need to issue your first
  send. Open `ws://host/<any-agent>/ws` and send `{"type":"call",
  "target":"kernel","payload":{"type":"reflect"},"id":"1"}`. If you
  find yourself reading `crates/fantastic-kernel/src/` or
  `crates/bundles/fantastic-web/src/` to figure out a transport URL
  — that's a primer regression. Stop and flag it.

## Stateful crates need a running `fantastic` daemon

Some crates hold state in process-memory that doesn't survive
separate one-shot CLI invocations:

- `fantastic-web` — the axum server instance.
- `fantastic-web-ws` — active WebSocket connections + per-client
  inbox queues.

Their selftests start a single `fantastic` and drive it over the WS
proxy (`ws://localhost:$PORT/<id>/ws`). Each selftest's pre-flight
defines a shell `call()` helper that wraps a one-shot WS round-trip
in inline Python (or any WS client of choice). Don't try to use the
`call` subcommand for these — one-shots spawn a fresh process and
can't see live in-memory state.

## Index

| File | Scopes | Requires |
|---|---|---|
| [`crates/fantastic-kernel/selftest.md`](crates/fantastic-kernel/selftest.md) | substrate, persistence | `cargo build --release` |
| [`crates/bundles/fantastic-core/selftest.md`](crates/bundles/fantastic-core/selftest.md) | substrate | running daemon |
| [`crates/bundles/fantastic-cli-bundle/selftest.md`](crates/bundles/fantastic-cli-bundle/selftest.md) | cli, rendering | tty |
| [`crates/bundles/fantastic-file/selftest.md`](crates/bundles/fantastic-file/selftest.md) | persistence, fs | running daemon |
| [`crates/bundles/fantastic-web/selftest.md`](crates/bundles/fantastic-web/selftest.md) | HTTP, rendering | free port |
| [`crates/bundles/fantastic-web-ws/selftest.md`](crates/bundles/fantastic-web-ws/selftest.md) | WS, transport | `fantastic-web` parent |
| [`crates/bundles/fantastic-web-rest/selftest.md`](crates/bundles/fantastic-web-rest/selftest.md) | HTTP, REST | `fantastic-web` parent |

Phase 1 selftests are CONTRACTS — they describe what each crate
must verify when its impl lands. The `compat.yml` CI workflow runs
the same set of probes against both the binary and the documented
spec; any drift fails the build.
