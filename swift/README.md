# Fantastic Kernel — Swift

Native Swift port of the Rust kernel in `../rust/`. Targets Apple
platforms (macOS, iOS, iPadOS, visionOS, tvOS, watchOS). The Rust
workspace remains the canonical implementation for non-Apple
deployments.

**Status: Phase 1 of 8 — foundation types only.** See "Phases" below
for the full roadmap.

## Why a Swift port

The Apple-platform app (`apple/`) consumes the Rust kernel via UniFFI
through two SPM packages (`FantasticKernelEmbedded`,
`FantasticKernelFull`). Several recent commits have been about making
the Rust↔Swift boundary thinner (FM bundle removal, CDN bundling,
inline GL). A native Swift kernel removes the boundary entirely on
Apple platforms while keeping the Rust kernel for non-Apple.

Vertical-integration wins:
- Direct `LanguageModelSession`, `AppIntents`, `WidgetKit`, `Vision`,
  `Speech`, `HealthKit`, `EventKit`, `SwiftData`, `CloudKit` access
  without UniFFI callback ceremony
- SwiftUI agents that ARE views, not just HTML in a WebView
- Xcode debugger across the whole stack
- Sandboxed by default with proper entitlements
- No XCFramework build pipeline

## Tiers (matching the Rust workspace)

| product | platforms | includes |
|---|---|---|
| `FantasticKernelEmbedded` | iOS, iPadOS, visionOS, tvOS, watchOS, sandboxed macOS | All bundles EXCEPT subprocess-using ones |
| `FantasticKernelFull` | macOS Pro (unsandboxed) | All bundles including `terminal_backend`, `local_runner`, `python_runtime`, `ssh_runner` |

Tier split expressed via SwiftPM products + `#if os(macOS)` guards on
subprocess-using bundle code.

## Phases

| phase | scope | LOC | status |
|---|---|---|---|
| 1 | Foundation — `JSON`, `AgentId`, `AgentRecord`, `BundleError` | ~700 | **landed** |
| 2 | Kernel — `Agent`, `Kernel` actor, `Bundle` protocol, `BundleRegistry`, `StorageMode`, `KernelState`, persistence, lock file, lifecycle | ~3,500 | next |
| 3 | Trivial bundles — `file`, `html_agent`, `gl_agent`, `scheduler`, `canvas_backend`, `canvas_webapp`, `ai_chat_webapp`, `terminal_webapp`, `kernel_bridge`, `telemetry_pane`, `cli_bundle`, `tools`, `proxy_agent` | ~5,000 | |
| 4 | HTTP layer — `web`, `web_ws`, `web_rest` via Hummingbird | ~2,900 | |
| 5 | LLM backends — `ollama_backend`, `nvidia_nim_backend` via URLSession AsyncBytes | ~3,700 | |
| 6 | Pro-tier (macOS-only) subprocess bundles — `terminal_backend`, `local_runner`, `python_runtime`, `ssh_runner` | ~4,100 | |
| 7 | CLI binary — `fantastic` executable | ~260 | |
| 8 | Migration — Swift kernel replaces XCFramework in the Apple app; UniFFI retired | — | |

Total: ~20k LOC of substantive Swift (the Rust side is 24k; UniFFI
bridge ~756 LOC vanishes in the port).

## Wire compatibility

Verb names stay snake_case strings in JSON. Payload shapes match the
Rust kernel byte-for-byte. This allows two concurrent kernels to
exchange messages via the `kernel_bridge` bundle during the migration
period.

`OrderedDictionary` (from swift-collections) backs the `JSON.object`
variant so `agent.json` byte-for-byte parity holds across Rust↔Swift.

## Building

```bash
cd swift
swift build
swift test           # 45 tests so far (Phase 1)
```

Requires Swift 6.0+ (Xcode 16+).

## Layout

```
swift/
  Package.swift                    SwiftPM workspace
  Sources/
    FantasticJSON/                 JSON enum + Codable + parser
    FantasticKernel/               AgentId, AgentRecord, BundleError (Phase 1)
                                   Agent, Kernel actor, Bundle protocol (Phase 2+)
  Tests/
    FantasticJSONTests/
    FantasticKernelTests/
  README.md                        this file
```

## Public API contract

The Swift kernel exposes the same method names + payload shapes as
the UniFFI surface today. The Apple app's `import FantasticKernel{Embedded,Full}`
lines and call sites stay unchanged through the migration; only the
underlying implementation (Rust XCFramework → native Swift) swaps.
Coordinated communication with `app-claude` before any breaking
change to:
- `Kernel.sendJson(targetId:payloadJson:)`
- `Kernel.sendJsonAs(senderId:targetId:payloadJson:)`
- `Kernel.proxyEmit(agentId:eventJson:)`
- `Kernel.registerProxyAgent(agentId:host:)`
- `Kernel.registerTool` / `unregisterToolsBySender` / `listToolsForLlm`
- `ProxyAgent` protocol (handle, onBoot, onDelete)
- HTTP routes (`/<agent_id>/`, `/<agent_id>/ws`, `/_assets/*`, `/transport.js`)
- Bundle names: `proxy_agent.tools`, `tools.tools`, `canvas_webapp.tools`,
  `canvas_backend.tools`, `web.tools`, etc.

## Third-party dependencies

- [swift-collections](https://github.com/apple/swift-collections) 1.1+ — `OrderedDictionary` for `JSON.object` key-order preservation
- (Phase 4) [Hummingbird](https://github.com/hummingbird-project/hummingbird) 2.x — HTTP server framework (closest axum analog in Swift)

## License

Apache-2.0, same as the rest of the project. See `../LICENSE`.
