# fantastic-canvas

A medium that unifies humans and AIs into a single workspace.
Recursive `Agent` nodes, one primitive (`send`), plugin-discovered
bundles. Every agent answers `{"type":"reflect"}` — the universal
discovery verb. No client library: the protocol IS the API.

## Two runtimes, one workdir

The kernel ships in two implementations that share the same on-disk
format (`.fantastic/`) and the same HTTP + WebSocket wire protocol:

```
fantastic_canvas/
├── python/    reference implementation — uvicorn + FastAPI, 510+ tests
└── rust/      drop-in port — axum + tokio, embeds into iOS/visionOS apps
```

- **Python** (`python/`) — the reference. Used today by the Pro Mac
  app and by anyone running fantastic on a server. Run with `cd
  python && uv sync && uv run fantastic`. See [`python/README.md`](python/README.md).
- **Rust** (`rust/`) — same behavior, fits inside a sandboxed iOS /
  iPadOS / visionOS app where Python can't run. Run with `cd rust
  && cargo run --release --bin fantastic`. See [`rust/README.md`](rust/README.md).

**One runtime is active per workdir at a time.** The existing
`.fantastic/lock.json` PID guard enforces it — there is no concurrent
mode, no bridge between them. Switching is a reboot: stop one daemon,
start the other against the same dir.

**Weak loading** keeps switching safe. If a persisted agent's
`handler_module` isn't installed in the active runtime, the kernel
logs one line to stderr and skips that agent on boot — same byte
shape across both kernels so CI and selftests can grep it:

    [kernel] skipping agent <id>: bundle <module> not installed in this runtime

The record stays on disk untouched. Reboot under the runtime that
has the bundle and the agent rehydrates intact. Wipe-and-rebuild
safe.

## Apple integration

The Swift app at
[`Alexadar/fantastic_app`](https://github.com/Alexadar/fantastic_app)
consumes either runtime through the same HTTP + WS surface:

- **FantasticPro** (macOS, unsandboxed) — spawns the kernel as a
  subprocess. Either runtime works as a drop-in; the app's launcher
  resolves `fantastic` from PATH or `~/.cargo/bin`.
- **FantasticLite** (macOS + iOS + iPadOS + visionOS, App Store
  sandboxed) — cannot spawn subprocesses, so the Python kernel is
  unreachable. The Rust runtime ships a Swift Package
  (`FantasticKernel`) that links the Rust kernel into the app process
  and binds a loopback `127.0.0.1:0` server the existing `WKWebView`
  points at. Zero changes to canvas frontend code.

See [`rust/README.md`](rust/README.md) for the SPM consumption story
and the bundle scoreboard.

## Repo layout

| path | content |
|---|---|
| [`python/`](python/) | reference kernel + 21 bundles + 530+ tests + selftests |
| [`rust/`](rust/) | production runtime — 21-of-21 bundle port, 205+ cargo tests, iOS-safe embedded slice |
| [`.github/workflows/`](.github/workflows/) | CI for both runtimes — `python-*.yml` (lint, tests) and `rust-*.yml` (build, xcframework, compat) |
| [`.claude/`](.claude/) | working notes and plans for Claude Code sessions |

## Status

|                            | Python                 | Rust                                  |
|----------------------------|------------------------|---------------------------------------|
| substrate                  | ✓ 530 tests            | ✓ 205+ tests                          |
| HTTP / WS / REST surfaces  | ✓                      | ✓ (single port, dynamic mount)        |
| WS binary frames (incl. chunked) | ✓ single-frame  | ✓ single + chunked uploads            |
| canvas in browser          | ✓                      | ✓                                     |
| LLM bundles (ollama / NIM) | ✓                      | ✓                                     |
| terminal_backend (PTY)     | ✓                      | ✓                                     |
| Swift embedded (Lite)      | n/a                    | ✓ UniFFI XCFramework + SPM            |
| Feature gates (full / embedded) | n/a               | ✓ subprocess bundles excluded from Lite |
| Cross-runtime workdir loading | ✓                   | ✓ (round-trip verified)               |
| Weak-load contract         | ✓                      | ✓ matches Python byte-for-byte        |

## Contributing

Both runtimes share the wire contract — any change that affects the
HTTP/WS protocol, the `.fantastic/` on-disk format, or the reflect
primer needs to land in both. Lint + test commands per runtime are
in the respective READMEs.

Commits and pushes require explicit consent per project convention.

## License

MIT. See [`python/LICENSE`](python/LICENSE).
