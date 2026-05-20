# fantastic-kernel

A medium that unifies humans and AIs into a single workspace.
Recursive `Agent` nodes, one primitive (`send`), plugin-discovered
bundles. Every agent answers `{"type":"reflect"}` — the universal
discovery verb. No client library: the protocol IS the API.

## Why Rust

Fits inside sandboxed iOS / iPadOS / visionOS apps, embeddable as a
static library + Swift package. Same workdir format and HTTP/WS
contract everywhere it runs — server, Mac desktop, iOS device.

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  SUBSTRATE  (crates/fantastic-kernel/)                                   │
│   Agent  — recursive node; .send / .emit / .create / .delete             │
│   Kernel — tree-wide ctx (flat agents index, state subs, bundle reg)     │
│   System verbs (create/delete/update/list_agents) baked into Agent.      │
└────────────────────────┬─────────────────────────────────────────────────┘
                         │  agent ⇌ agent ⇌ agent (agent.send)
       ┌─────────────────┼─────────────────────────────┐
       ▼                 ▼                             ▼
   ┌────────┐      ┌────────────┐              ┌────────────────┐
   │ core   │      │ web        │              │ (future)       │
   │ cli    │      │ (axum)     │              │ canvas / ai /  │
   │ file   │      │ HTTP + WS  │              │ terminal ...   │
   │ ...    │      │ transport  │              │                │
   └────────┘      └─────┬──────┘              └────────────────┘
                         │
                         ▼ HTTP + WS frames (text + binary)
   ┌─────────────────────────────────────────────────────────────────────┐
   │                       BROWSER / WKWebView                           │
   │  iframe ↔ iframe bus, transport.js auto-injected on every page.     │
   └─────────────────────────────────────────────────────────────────────┘
```

## Run

Phase 1 scaffold today — the binary builds and prints a status line:

```bash
cd rust
cargo build --release --bin fantastic
./target/release/fantastic
```

Once the substrate impl lands (task #228) and the Phase 1 bundles
follow (task #229), invocation is:

```bash
fantastic                                              # boot all persisted, daemon if a web agent exists
fantastic <id> <verb> [k=v ...]                        # one-shot RPC
fantastic reflect [<id>]                               # shorthand: <id> reflect (default: kernel)
fantastic core create_agent handler_module=web.tools port=8888    # persist a web record
```

Composition rule: `fantastic` blocks only when the workdir has a
`web` agent persisted (HTTP daemon) or `stdin` is a tty (REPL).
Otherwise it exits silently.

## Workspace layout

```
rust/
├── Cargo.toml                         workspace root
├── crates/
│   ├── fantastic-kernel/              substrate (Agent + Kernel + send/emit/watch/reflect)
│   ├── fantastic-bundle/              plugin trait every bundle re-exports
│   ├── fantastic-cli/                 the `fantastic` binary
│   ├── fantastic-uniffi/              Swift binding (Phase 3)
│   └── bundles/
│       ├── fantastic-core/            root orchestrator (id="core")
│       ├── fantastic-cli-bundle/      stdout renderer
│       ├── fantastic-file/            fs-as-agent
│       ├── fantastic-web/             axum HTTP host
│       ├── fantastic-web-ws/          WS verb channel
│       └── fantastic-web-rest/        REST verb channel
├── scripts/
│   ├── build-cli.sh                   cargo build --release --bin fantastic
│   ├── build-xcframework.sh           Phase 3 — Fantastic.xcframework for SPM
│   └── compat-python.sh               black-box compat probes
└── packaging/
    └── FantasticKernel/               Phase 3 — Swift package wrapping the XCFramework
```

## Bundle map (Phase 1 set)

| crate | role |
|---|---|
| `fantastic-core` | root orchestrator |
| `fantastic-cli-bundle` | stdout renderer (ephemeral) |
| `fantastic-file` | filesystem-as-agent |
| `fantastic-web` | HTTP host (axum) |
| `fantastic-web-ws` | WS verb channel (tokio-tungstenite) |
| `fantastic-web-rest` | REST verb channel |

Phase 2 adds `fantastic-html-agent`, `fantastic-canvas-backend`,
`fantastic-canvas-webapp`.

## Plugin model

Bundles register at **compile time** — the CLI crate links the
default set in; the `fantastic-uniffi` crate links only what's
allowed on the platform. iOS forbids dynamic loading in sandboxed
apps, so the compile-time model is the only fully-portable option.

Optional dynamic loading (`libloading::Library` over
`installed_agents/*/lib*.dylib`) is gated behind a non-iOS feature
flag — preserves the `fantastic install-bundle <git+url>` UX on
servers + unsandboxed desktops.

## Wire surface

The Swift app, browsers, LLM clients consume the kernel through
HTTP + WebSocket:

- **HTTP** `/`, `/<id>/`, `/<id>/file/<path>`, `/transport.js`.
- **WS `/<id>/ws`** — text frames: `call` / `emit` / `watch` /
  `unwatch` / `reply` / `error` / `event`. Binary frames carry
  byte-heavy payloads as `[4-byte BE u32 H][JSON header][raw blob]`.
- **`.fantastic/`** — on-disk records (`agent.json` per agent,
  `lock.json` with the daemon's PID).

A black-box `scripts/compat-python.sh` runs the wire-protocol probes
against the running binary; CI fails on any divergence from the
documented contract.

## Weak loading

If a persisted agent's `handler_module` isn't registered in this
runtime's bundle set, log one line to stderr and skip the agent on
boot:

    [kernel] skipping agent <id>: bundle <module> not installed in this runtime

The record stays on disk untouched. Install the bundle (or boot
under a runtime that has it) and the agent rehydrates intact.
Wipe-and-rebuild safe.

## Swift embedding (Phase 3)

The `fantastic-uniffi` crate exposes a small lifecycle API:

```idl
namespace fantastic {
    [Async, Throws=KernelError]
    Kernel start_kernel(string workdir, u16 port_hint);
};

interface Kernel {
    [Async, Throws=KernelError]
    string send_json(string target_id, string payload_json);
    u16 http_port();
    void shutdown();
};
```

The canonical Swift↔kernel API stays HTTP + WS — UniFFI is only used
for lifecycle (start/stop, port discovery). Swift code:

```swift
let kernel = try await Fantastic.startKernel(workdir: appGroupURL.path, portHint: 0)
let port = kernel.httpPort()
// open WKWebView at http://127.0.0.1:\(port)/<canvas_id>/
```

Built via `cargo build --target …` for each Apple slice
(`aarch64-apple-ios`, `aarch64-apple-ios-sim`,
`x86_64-apple-ios-sim`, `aarch64-apple-darwin`, `x86_64-apple-darwin`)
plus `xcodebuild -create-xcframework`. Distributed as the SPM package
at `packaging/FantasticKernel/`.

UniFFI v0.29 — async-native, `Result<T, E>` → Swift `throws`,
XCFramework + SPM distribution used by Firefox iOS in production.

## Pre-push checks

```bash
cd rust
cargo check --workspace
cargo clippy --workspace -- -D warnings
cargo test --workspace
```

CI runs these on Linux + macOS via `.github/workflows/rust-build.yml`.

## License

MIT.
