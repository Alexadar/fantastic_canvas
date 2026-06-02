# fantastic-kernel

A medium that unifies humans and AIs into a single workspace.
Recursive `Agent` nodes, one primitive (`send`), compile-time-linked
bundles. Every agent answers `{"type":"reflect"}` — the universal
discovery verb. No client library: the protocol IS the API.

## Status

Production runtime — full parity with the Python reference kernel.

|                                              | value                                   |
|----------------------------------------------|-----------------------------------------|
| Python bundles ported                        | **21 / 21**                             |
| Cargo tests passing                          | **203** (workspace, default features)   |
| `./scripts/quality.sh`                       | 8 / 8 PASS (compile, fmt, clippy, test, deny, audit, machete, tree) |
| Feature gates                                | `full` (default) / `embedded` (no-subprocess) |
| Embedded slice (`cli --no-default-features --features embedded`) | clean compile, subprocess-using bundles excluded |
| Cross-runtime workdir                        | byte-identical `.fantastic/` round-trip |
| Cold start                                   | 30 / 30 / 88 ms (virgin / hydrate / boot-to-listening) |
| Prebuilt binaries                            | 4 targets (macOS arm64+x86_64, Linux x86_64+aarch64) via [RELEASING.md](RELEASING.md) |

## Why Rust

A single portable native binary — same workdir format and HTTP / WS
contract everywhere it runs (server, Mac desktop, Linux). Pure Rust:
no foreign-language bindings.

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
   │ core   │      │ web        │              │ canvas / ai /  │
   │ cli    │      │ (axum)     │              │ terminal /     │
   │ file   │      │ HTTP+WS+   │              │ scheduler /    │
   │ ...    │      │ REST       │              │ runners / ...  │
   └────────┘      └─────┬──────┘              └────────────────┘
                         │
                         ▼ HTTP + WS frames (text + binary, chunked supported)
   ┌─────────────────────────────────────────────────────────────────────┐
   │                       BROWSER / WKWebView                           │
   │  iframe ↔ iframe bus, transport.js auto-injected on every page.     │
   └─────────────────────────────────────────────────────────────────────┘
```

## Run

```bash
cd rust
cargo build --release --bin fantastic
BIN=$(pwd)/target/release/fantastic

# One-shot RPCs:
$BIN reflect                                  # reflect on root (id="core")
$BIN reflect kernel                           # discovery primer (URLs, bundles, agents)
$BIN core list_agents                         # every agent in this workdir
$BIN core create_agent handler_module=web.tools id=w port=8888

# Daemon mode (blocks if a `web` agent is persisted in the workdir):
$BIN
# → "fantastic: daemon up. N agent(s) loaded. Ctrl-C to stop."
```

Composition rule: `fantastic` blocks only when the workdir has a
`web` agent persisted (HTTP daemon) or `stdin` is a tty (REPL).
Otherwise it exits silently.

## Feature gates

Two compile-time tiers gate which bundles ship in the binary:

```toml
default = ["full"]
full     # CLI + server + macOS Pro + Linux unsandboxed
embedded # iOS Lite, iPadOS, visionOS, sandboxed macOS
```

**`full`** includes every ported bundle. Subprocess-spawning bundles
(`terminal_backend`, `python_runtime`, `local_runner`, `ssh_runner`)
and the SSH transport in `kernel_bridge` are gated to this feature.

**`embedded`** compiles without any subprocess code. iOS app sandboxes
forbid `fork()` / `Process` / dynamic library loading; the embedded
slice excludes anything that touches them at compile time. 17 of 21
bundles ship under embedded — the iOS-safe ceiling.

Switch with `--no-default-features --features embedded`:

```bash
cargo check  -p fantastic-cli    --no-default-features --features embedded
```

Passes clean — that's the contract the sandboxed/no-subprocess tier
ships against.

## Bundle map (17 of 17)

The frontend ships no native view bundles — it is served generically
from `ts/dist` via a `file` agent (the host never names the frontend).

iOS-safe bundles (compile under either tier):

| crate                       | role                                                          |
|-----------------------------|---------------------------------------------------------------|
| `fantastic-core`            | root orchestrator (id="core")                                 |
| `fantastic-cli-bundle`      | stdout renderer (ephemeral, tty-only)                         |
| `fantastic-file`            | filesystem-as-agent                                           |
| `fantastic-web`             | axum HTTP host + WS + REST (dynamic mounting)                 |
| `fantastic-web-ws`          | WS verb-channel routes (mounted onto parent web)              |
| `fantastic-web-rest`        | REST verb-channel routes (mounted onto parent web)            |
| `fantastic-scheduler`       | tokio-tick recurring tasks via file_agent_id persistence      |
| `fantastic-ollama-backend`  | local LLM via ollama; LLM contract reference impl             |
| `fantastic-nvidia-nim-backend` | NVIDIA NIM LLM (OpenAI-compatible, api_key sidecar, 429 retry) |
| `fantastic-kernel-bridge`   | cross-kernel comms over memory / WS (asymmetric, WS-only)      |

Full-tier-only bundles (subprocess; excluded from embedded slice):

| crate                       | role                                                          |
|-----------------------------|---------------------------------------------------------------|
| `fantastic-terminal-backend`| PTY shell + flow control + UTF-8 + image-paste over binary WS |
| `fantastic-python-runtime`  | subprocess `python -c <code>` with interpreter resolution ladder |
| `fantastic-local-runner`    | supervises a child `fantastic` in another workdir             |
| `fantastic-ssh-runner`      | remote `fantastic` lifecycle + canvas-iframing tunnel         |
| `fantastic-kernel-bridge` (SSH transport) | `ssh -L` tunnel chained over WsTransport          |

## Workspace layout

```
rust/
├── Cargo.toml                         workspace root
├── crates/
│   ├── fantastic-kernel/              substrate (Agent + Kernel + send/emit/watch/reflect)
│   ├── fantastic-bundle/              bundle trait every bundle re-exports
│   ├── fantastic-cli/                 the `fantastic` binary
│   └── bundles/
│       ├── fantastic-core/                root orchestrator
│       ├── fantastic-cli-bundle/          stdout renderer
│       ├── fantastic-file/                fs-as-agent
│       ├── fantastic-web/                 axum host + WS/REST router
│       ├── fantastic-web-ws/              WS verb channel
│       ├── fantastic-web-rest/            REST verb channel
│       ├── fantastic-scheduler/           recurring tasks
│       ├── fantastic-ollama-backend/      local LLM
│       ├── fantastic-nvidia-nim-backend/  NVIDIA NIM LLM
│       ├── fantastic-kernel-bridge/       cross-kernel comms
│       ├── fantastic-terminal-backend/    PTY  (full-tier only)
│       ├── fantastic-python-runtime/      python -c (full-tier only)
│       ├── fantastic-local-runner/        supervises child fantastic (full-tier)
│       └── fantastic-ssh-runner/          remote fantastic via SSH (full-tier)
├── scripts/
│   ├── build-cli.sh                       cargo build --release --bin fantastic
│   ├── bench-coldstart.sh                 3-metric boot benchmark
│   ├── quality.sh                         canonical pre-push gate
│   └── compat-python.sh                   black-box wire-protocol probes
├── selftest.md                            index + Rust-overlay specs
└── selftest/                              Rust-specific selftest overlays
```

## Bundle model

Bundles register at **compile time** — the CLI crate links the
default set; the `embedded` feature links the no-subprocess subset.
Adding a bundle to a build means adding its crate to the workspace
and calling `reg.register(...)` in the relevant
`register_default_bundles()` site.

## Wire surface

Browsers, embedding apps, and LLM clients consume the kernel through
HTTP + WebSocket:

- **HTTP** `/`, `/<id>/`, `/<id>/file/<path>`, `/transport.js`.
- **WS `/<id>/ws`** — text frames: `call` / `emit` / `watch` /
  `unwatch` / `reply` / `error` / `event`. **Binary frames** carry
  byte-heavy payloads as `[4-byte BE u32 hdr_len][JSON header][raw blob]`.
  Opt-in chunked uploads (`upload_id` + `chunk_index` + `total_chunks` +
  `final` in the header) reassemble server-side; per-WS state means
  abandoned uploads drop on disconnect.
- **REST** `POST /<rest_id>/<target_id>` body=payload → `kernel.send` → JSON.
  `GET /<rest_id>/_reflect[/<target_id>]` for static discovery.
- **`.fantastic/`** — disk-mode workdir state. Python-compatible
  per-agent layout: `agent.json` for the root + `agents/<id>/agent.json`
  recursively for every child. `lock.json` holds the daemon's PID.
  Bundle-local sidecar files (chat history, scheduler state, etc.)
  live next to each agent's `agent.json` in its dir.

## State medium — save/load foundation

The kernel's whole agent tree is materializable as a serializable
[`KernelState`] in RAM — never as a file on disk. Two storage modes
pick the *medium*:

| mode | what it does | when |
|---|---|---|
| `StorageMode::Disk(workdir)` | Adapter mirrors each agent record onto `<workdir>/.fantastic/agents/<id>/agent.json`. **Dirty binding**: persistence merges kernel-managed fields into the existing JSON — never wholesale-overwrites, never touches sidecar files. Bundles reconcile their own slices when they next touch them. | The standalone CLI; the workspace-kernel embed (Pro Mac, anyone holding a folder). |
| `StorageMode::InMemory` | No filesystem I/O ever. State lives only in `kernel.agents`. The consumer extracts a snapshot via `kernel.save() -> KernelState` and restores via `kernel.load(state)`. | An embedding app's in-RAM "brain" kernel — always running, never touches disk, snapshot persists externally. |

Both modes share the same save/load API. The only difference is
the medium — disk mode also mirrors each agent record to its
`agent.json` on every mutation:

```rust
let snapshot: KernelState = kernel.save();          // both modes (pure read)
let json: String          = kernel.save_json();     // both modes (JSON snapshot)
kernel.load(snapshot)?;                              // both modes (replace tree)
kernel.load_json(&json)?;                            // both modes (parse + replace)
```

`save_json()` output is byte-deterministic for equal in-memory state
(agents sorted by id), so it composes with content-addressed storage
and `diff`-style review.

A black-box `scripts/compat-python.sh` runs wire-protocol probes
against the running binary; CI fails on any divergence.

## Cross-runtime workdir compatibility

Same `.fantastic/` directory loads under either Python or Rust
kernel. Records hydrate from identical per-agent `agent.json` JSON.
Bundles missing in one runtime log a single skip line and the boot
continues:

    [kernel] skipping agent <id>: bundle <module> not installed in this runtime

Wire-identical across runtimes — AI agents grep this line so the
exact string is contract.

Python's `python_runtime` auto-fills `meta.python = sys.executable`
on first boot if neither `python` nor `venv` is set; that's the
durable record both runtimes hit on subsequent opens, so cross-
runtime interpreter resolution is deterministic.

See [`selftest/cross_runtime_workdir.md`](selftest/cross_runtime_workdir.md)
for the round-trip test plan.

## Cold start

Release binary's boot budget, measured by `scripts/bench-coldstart.sh`:

| metric                    | target  | latest |
|---------------------------|---------|--------|
| virgin-dir reflect        |  50 ms  |  30 ms |
| 18-agent hydrate reflect  | 100 ms  |  30 ms |
| boot-to-listening (HTTP)  | 200 ms  |  88 ms |

Captured on macOS arm64 (M-series) in release mode against a fresh
tempdir. CI runs the same script with 2× ceilings via
`FANTASTIC_BENCH_RELAXED=1` to absorb cloud-runner variance.

Run locally:

```bash
cd rust
cargo build --release --bin fantastic
./scripts/bench-coldstart.sh
```

## Selftests

Most user-facing behaviour is identical across Python and Rust
runtimes — Python's per-bundle selftests under
[`../python/bundled_agents/*/selftest.md`](../python/bundled_agents/)
drive the wire surface against either binary by swapping `PATH`.

Rust-specific behaviour lives in [`selftest/`](selftest/):

- `feature_gates.md` — `full` vs `embedded` compile matrix
- `python_runtime_resolution.md` — the 8-step interpreter ladder
- `binary_frame_chunking.md` — chunked WS uploads protocol
- `cross_runtime_workdir.md` — round-trip workdir loading

See [`selftest.md`](selftest.md) for the index + driving workflow.

## Pre-push checks

> **Working with Claude on this repo?** Run `./scripts/quality.sh`
> (or its individual sections) before every commit you ask Claude
> to make. Claude SHOULD pick the strictest tools available — clippy
> with `-D warnings`, `cargo fmt --check`, `cargo deny`, strict YAML
> parsing on workflow edits — so CI doesn't surface lint issues
> the local toolchain quietly accepted (Rust toolchain version
> skew has burned us twice). No git hooks installed by design;
> the gate is operator-driven via the script + Claude's own
> pre-commit sweep.

Single command — `./scripts/quality.sh` runs the canonical gate
(8 sections): `compile`, `fmt`, `clippy`, `test`, `deny`, `audit`,
`machete`, `tree`. See the script header for what each does and
`--install` for fetching missing tools (`cargo-deny`, `cargo-audit`,
`cargo-machete`).

```bash
cd rust
./scripts/quality.sh                    # default — skip missing tools
./scripts/quality.sh --install          # install missing tools first
./scripts/quality.sh --section deny     # run one section only
```

The longer breakdown still works if you want to drive sections by hand:

```bash
cargo check --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
cargo test --workspace
cargo check -p fantastic-cli --no-default-features --features embedded
./scripts/compat-python.sh
./scripts/bench-coldstart.sh
```

CI runs the workspace tests on Linux + macOS via
`.github/workflows/rust-build.yml`. Release builds (4-target tarballs)
are driven by `.github/workflows/release-rust.yml` — see
[`RELEASING.md`](RELEASING.md) for how to cut a release.

## License

MIT.
