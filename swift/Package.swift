// swift-tools-version: 6.0
//
// Fantastic Kernel — Swift workspace.
//
// Mirrors the Rust workspace in `rust/` for Apple-platform deployment.
// Public API contract follows the UniFFI surface today exposed by
// `rust/packaging/FantasticKernel{Embedded,Full}` so the iOS/macOS app
// can stay on its current import lines while the implementation moves
// from a Rust XCFramework to native Swift.
//
// Tiers (mirror Rust's `embedded` / `full` Cargo features):
//   - FantasticKernelEmbedded — sandbox-safe; ships in iOS / iPadOS /
//     visionOS / tvOS / watchOS / sandboxed macOS targets
//   - FantasticKernelFull — adds macOS-only subprocess-using bundles
//     (terminal_backend, local_runner, python_runtime, ssh_runner)
//
// Phase 1 (this file's initial state) ships only the foundation types
// — JSON, AgentId, AgentRecord, BundleError. The Kernel actor, bundles,
// and HTTP layer arrive in subsequent phases.

import PackageDescription

let package = Package(
    name: "FantasticKernel",
    platforms: [
        .macOS(.v14),
        .iOS(.v17),
        .visionOS(.v1),
        .tvOS(.v17),
        .watchOS(.v10),
    ],
    products: [
        .library(name: "FantasticJSON", targets: ["FantasticJSON"]),
        .library(name: "FantasticKernel", targets: ["FantasticKernel"]),
    ],
    dependencies: [
        // OrderedCollections preserves JSON object key order on
        // round-trip — matches Rust's `serde_json::Map<String, Value>`
        // with the `preserve_order` feature. Required so `agent.json`
        // bytes are stable across Rust↔Swift cross-runtime testing.
        .package(url: "https://github.com/apple/swift-collections.git", from: "1.1.0"),
    ],
    targets: [
        // ── FantasticJSON ─────────────────────────────────────────
        // Dynamic JSON value type for the kernel's substrate-level
        // dispatch (every verb takes/returns arbitrary JSON). Mirrors
        // `serde_json::Value`.
        .target(
            name: "FantasticJSON",
            dependencies: [
                .product(name: "OrderedCollections", package: "swift-collections"),
            ]
        ),
        .testTarget(
            name: "FantasticJSONTests",
            dependencies: ["FantasticJSON"]
        ),

        // ── FantasticKernel ───────────────────────────────────────
        // Phase 1: foundation types only (AgentId, AgentRecord,
        // BundleError). Phase 2 adds Agent, Kernel actor,
        // BundleRegistry, StorageMode, KernelState, persistence,
        // lock file, lifecycle, reflect, save/load.
        .target(
            name: "FantasticKernel",
            dependencies: [
                "FantasticJSON",
                .product(name: "OrderedCollections", package: "swift-collections"),
            ]
        ),
        .testTarget(
            name: "FantasticKernelTests",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
    ]
)
