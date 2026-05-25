# Fantastic Kernel — Swift

Native Swift kernel for Apple platforms. macOS, iOS, iPadOS,
visionOS, tvOS, watchOS. Used in-process by the Apple app — no
UniFFI, no XCFramework, no native subprocess required.

The reference kernel for non-Apple deployments is in
[`../python/`](../python/). Wire format + on-disk shape are
byte-compatible between them.

## What's in the box

- 1 substrate target (`FantasticKernel`) — actor-based agent
  store, system verbs, persistence, lock-file workdir guard
- 1 JSON target (`FantasticJSON`) — `OrderedDictionary`-backed
  variant so on-disk JSON matches Python's `dict` key order
- 1 bootstrap target (`FantasticKernelStartup`) — `startKernel(...)`
  / `startKernelInMemory(...)` entry points
- 16 bundle targets — see scoreboard below
- 1 CLI executable (`fantastic`)
- 122 tests across substrate, bundles, parity harness, public-API
  shim

## Tiers

| product | platforms | includes |
|---|---|---|
| `FantasticKernelEmbedded` | iOS, iPadOS, visionOS, tvOS, watchOS, sandboxed macOS | All bundles EXCEPT subprocess-using ones |
| `FantasticKernelFull` | macOS Pro (unsandboxed) | All bundles including `terminal_backend`, `local_runner`, `python_runtime`, `ssh_runner` |

Tier split expressed via SwiftPM products + `#if os(macOS)` guards on
the subprocess-using bundle code. The umbrella wrapper packages that
the Apple app consumes live under `swift/packaging/` (gitignored —
materialized locally; the app vendors its own copies).

## Bundle scoreboard

| bundle | target | tier | role |
|---|---|---|---|
| file | `FantasticFile` | both | sandboxed file storage |
| proxy_agent | `FantasticProxyAgent` | both | host-implemented agents (LanguageModel, etc.) |
| tools | `FantasticTools` | both | LLM tool registry |
| html_agent | `FantasticHtmlAgent` | both | HTML surface agent |
| gl_agent | `FantasticGlAgent` | both | WebGL surface agent |
| scheduler | `FantasticScheduler` | both | cron / interval triggers |
| canvas_backend | `FantasticCanvasBackend` | both | spatial workspace state |
| canvas_webapp | `FantasticCanvasWebapp` | both | canvas frontend at `/<id>/` |
| ai_chat_webapp | `FantasticAiChatWebapp` | both | chat UI, provider-agnostic |
| terminal_webapp | `FantasticTerminalWebapp` | both | xterm.js frontend |
| telemetry_pane | `FantasticTelemetryPane` | both | event firehose UI |
| cli_bundle | `FantasticCliBundle` | both | scripted-CLI surface |
| kernel_bridge | `FantasticKernelBridge` | both | in-memory + WS + HTTP transports |
| web | `FantasticWeb` | both | HTTP + WS server (Network.framework) |
| ollama_backend | `FantasticOllamaBackend` | both | local LLM, URLSession AsyncBytes SSE |
| nvidia_nim_backend | `FantasticNvidiaNimBackend` | both | hosted LLM, SSE + bearer auth + 429 retry |
| local_runner | `FantasticLocalRunner` | Pro | macOS-only — Process subprocess |
| python_runtime | `FantasticPythonRuntime` | Pro | macOS-only — embedded Python |
| ssh_runner | `FantasticSshRunner` | Pro | macOS-only — `ssh -L` tunnel |
| terminal_backend | `FantasticTerminalBackend` | Pro | macOS-only — `forkpty` + DispatchIO |

## Wire compatibility

Verb names stay snake_case strings in JSON. Payload shapes match the
Python kernel byte-for-byte. The `kernel_bridge` bundle's in-process
transport pairs two kernels (e.g. Swift ↔ Python) for end-to-end
mixed-runtime tests.

`OrderedDictionary` (from swift-collections) backs the `JSON.object`
variant so `agent.json` byte-for-byte parity holds across runtimes.

## Building

```bash
cd swift
swift build
swift test                              # full suite
swift test --filter FantasticKernel     # substrate only
RUST_KERNEL_BIN=<path> swift test \
    --filter FantasticParityTests       # cross-runtime parity (optional)
```

Requires Swift 6.0+ (Xcode 16+).

## Layout

```
swift/
  Package.swift                        SwiftPM workspace
  Sources/
    FantasticJSON/                     JSON enum + parser
    FantasticKernel/                   Agent, Kernel actor, Bundle protocol,
                                       BundleRegistry, persistence, lock, system verbs
    FantasticKernelStartup/            startKernel / startKernelInMemory
    FantasticWeb/                      HTTP + WS server (Network.framework)
    FantasticOllamaBackend/            local LLM SSE
    FantasticNvidiaNimBackend/         hosted LLM SSE
    Fantastic{Canvas,AiChat,Terminal,Telemetry}{Backend,Webapp,Pane}/
                                       UI + state bundles
    Fantastic{File,ProxyAgent,Tools,HtmlAgent,GlAgent,Scheduler,
              CliBundle,KernelBridge}/
                                       supporting bundles
    Fantastic{Terminal,Local,Python,Ssh}{Backend,Runner,Runtime}/
                                       macOS-only Pro-tier bundles
    Fantastic/                         `fantastic` CLI executable
  Tests/
    Fantastic*Tests/                   per-target unit suites
    FantasticParityTests/              cross-runtime byte-diff harness
  packaging/                           Apple app wrapper SPM packages (gitignored)
  docs/
    CROSS_ANALYSIS.md                  capability matrix vs the historical Rust port
    MIGRATION.md                       how the Apple app dropped UniFFI for native Swift
```

## Public API contract

The Swift kernel exposes the same method names + payload shapes the
Apple app already consumes (preserved from the historical UniFFI
surface to keep the app's import lines unchanged through the
migration). Coordinated communication with `app-claude` before any
breaking change to:
- `Kernel.sendJson(targetId:payloadJson:)`
- `Kernel.sendJsonAs(senderId:targetId:payloadJson:)`
- `Kernel.proxyEmit(agentId:eventJson:)`
- `Kernel.registerProxyAgent(agentId:host:)`
- `Kernel.registerTool` / `unregisterToolsBySender` / `listToolsForLlm`
- `ProxyAgent` protocol (`handle`, `onBoot`, `onDelete`)
- HTTP routes (`/<agent_id>/`, `/<agent_id>/ws`, `/_assets/*`,
  `/transport.js`)
- Bundle names: `proxy_agent.tools`, `tools.tools`,
  `canvas_webapp.tools`, `canvas_backend.tools`, `web.tools`, etc.

## Third-party dependencies

- [swift-collections](https://github.com/apple/swift-collections) 1.1+
  — `OrderedDictionary` for `JSON.object` key-order preservation

That's it — no Hummingbird, no Vapor, no NIO directly. HTTP + WS run
on `Network.framework`; LLM backends run on `URLSession.AsyncBytes`.

## License

Apache-2.0, same as the rest of the project. See `../LICENSE`.
