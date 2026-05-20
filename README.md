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
  subprocess. Today the Python kernel; in Phase 2 of the Rust port,
  the Rust binary becomes a drop-in.
- **FantasticLite** (macOS + iOS + iPadOS + visionOS, App Store
  sandboxed) — cannot spawn subprocesses, so the Python kernel is
  unreachable. Phase 3 of the Rust port ships a Swift Package
  (`FantasticKernel`) that links the Rust kernel into the app process
  and binds a loopback `127.0.0.1:0` server the existing `WKWebView`
  points at. Zero changes to canvas frontend code.

See [`rust/README.md`](rust/README.md) for the SPM consumption story
and the porting roadmap.

## Repo layout

| path | content |
|---|---|
| [`python/`](python/) | reference kernel + 20+ bundles + 510+ tests + selftests |
| [`rust/`](rust/) | Rust port (Phase 1 scaffold; full impl tracked under [`.claude/plans/`](.claude/plans)) |
| [`.github/workflows/`](.github/workflows/) | CI for both runtimes — `python-*.yml` (lint, tests) and `rust-*.yml` (build, xcframework, compat) |
| [`.claude/`](.claude/) | working notes and plans for Claude Code sessions |

## Status

| | Python | Rust |
|---|---|---|
| substrate | ✓ 510 tests | scaffold compiles |
| HTTP/WS surfaces | ✓ | pending Phase 1 |
| canvas in browser | ✓ | pending Phase 2 |
| Swift embedded (Lite) | n/a | pending Phase 3 |
| weak-load contract | ✓ | matches Python |

## Contributing

Both runtimes share the wire contract — any change that affects the
HTTP/WS protocol, the `.fantastic/` on-disk format, or the reflect
primer needs to land in both. Lint + test commands per runtime are
in the respective READMEs.

Commits and pushes require explicit consent per project convention.

## License

MIT. See [`python/LICENSE`](python/LICENSE).
