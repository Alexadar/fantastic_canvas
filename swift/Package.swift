// swift-tools-version: 6.0
//
// Fantastic Kernel — Swift workspace.
//
// Mirrors the Rust workspace in `rust/` for Apple-platform deployment.
// Public API contract follows the UniFFI surface today exposed by
// `rust/packaging/FantasticKernel{Embedded,Full}` so the iOS/macOS app
// can stay on its current import lines while the implementation moves
// from a Rust XCFramework to native Swift.

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
        .library(name: "FantasticBundles", targets: [
            "FantasticFile",
            "FantasticProxyAgent",
            "FantasticTools",
            "FantasticHtmlAgent",
            "FantasticGlAgent",
            "FantasticScheduler",
            "FantasticCanvasBackend",
            "FantasticCanvasWebapp",
            "FantasticAiChatWebapp",
            "FantasticTerminalWebapp",
            "FantasticTelemetryPane",
            "FantasticCliBundle",
            "FantasticKernelBridge",
            "FantasticWeb",
            "FantasticOllamaBackend",
            "FantasticNvidiaNimBackend",
        ]),
        .library(name: "FantasticKernelStartup", targets: ["FantasticKernelStartup"]),
        .executable(name: "fantastic", targets: ["Fantastic"]),
    ],
    dependencies: [
        .package(url: "https://github.com/apple/swift-collections.git", from: "1.1.0"),
    ],
    targets: [
        // ── Core ─────────────────────────────────────────────────
        .target(
            name: "FantasticJSON",
            dependencies: [.product(name: "OrderedCollections", package: "swift-collections")]
        ),
        .testTarget(name: "FantasticJSONTests", dependencies: ["FantasticJSON"]),

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

        // ── Trivially-portable bundles (Phase 3) ─────────────────
        .target(
            name: "FantasticFile",
            dependencies: ["FantasticKernel", "FantasticJSON",
                           .product(name: "OrderedCollections", package: "swift-collections")]
        ),
        .target(
            name: "FantasticProxyAgent",
            dependencies: ["FantasticKernel", "FantasticJSON",
                           .product(name: "OrderedCollections", package: "swift-collections")]
        ),
        .target(
            name: "FantasticTools",
            dependencies: ["FantasticKernel", "FantasticJSON",
                           .product(name: "OrderedCollections", package: "swift-collections")]
        ),
        .target(
            name: "FantasticHtmlAgent",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticGlAgent",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticScheduler",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticCanvasBackend",
            dependencies: ["FantasticKernel", "FantasticJSON",
                           .product(name: "OrderedCollections", package: "swift-collections")]
        ),
        .target(
            name: "FantasticCanvasWebapp",
            dependencies: ["FantasticKernel", "FantasticJSON"],
            resources: [.copy("Resources/canvas.html")]
        ),
        .target(
            name: "FantasticAiChatWebapp",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticTerminalWebapp",
            dependencies: ["FantasticKernel", "FantasticJSON"],
            resources: [.copy("Resources/index.html")]
        ),
        .target(
            name: "FantasticTelemetryPane",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticCliBundle",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticKernelBridge",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticWeb",
            dependencies: ["FantasticKernel", "FantasticJSON"],
            resources: [
                .copy("Resources/three.module.js"),
                .copy("Resources/xterm.min.js"),
                .copy("Resources/xterm.min.css"),
                .copy("Resources/xterm-addon-fit.min.js"),
                .copy("Resources/transport.js"),
            ]
        ),

        // ── LLM backends (Phase 5 / 8D) ──────────────────────────
        .target(
            name: "FantasticOllamaBackend",
            dependencies: ["FantasticKernel", "FantasticJSON",
                           .product(name: "OrderedCollections", package: "swift-collections")]
        ),
        .target(
            name: "FantasticNvidiaNimBackend",
            dependencies: ["FantasticKernel", "FantasticJSON",
                           .product(name: "OrderedCollections", package: "swift-collections")]
        ),

        // ── Pro-tier subprocess bundles (macOS only) ─────────────
        .target(
            name: "FantasticLocalRunner",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticPythonRuntime",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticSshRunner",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),
        .target(
            name: "FantasticTerminalBackend",
            dependencies: ["FantasticKernel", "FantasticJSON"]
        ),

        // ── Startup layer (Phase 8A) ─────────────────────────────
        // Composes the default bundle set + exposes
        // startKernelInMemory / startKernel free functions matching
        // the Rust UniFFI surface. App-facing entry point.
        .target(
            name: "FantasticKernelStartup",
            dependencies: [
                "FantasticKernel", "FantasticJSON",
                "FantasticFile", "FantasticProxyAgent", "FantasticTools",
                "FantasticHtmlAgent", "FantasticGlAgent", "FantasticScheduler",
                "FantasticCanvasBackend", "FantasticCanvasWebapp",
                "FantasticAiChatWebapp", "FantasticTerminalWebapp",
                "FantasticTelemetryPane", "FantasticCliBundle",
                "FantasticKernelBridge", "FantasticWeb",
                "FantasticOllamaBackend", "FantasticNvidiaNimBackend",
                "FantasticLocalRunner", "FantasticPythonRuntime",
                "FantasticSshRunner", "FantasticTerminalBackend",
            ]
        ),
        .testTarget(
            name: "FantasticKernelStartupTests",
            dependencies: [
                "FantasticKernelStartup", "FantasticKernel", "FantasticJSON",
                "FantasticProxyAgent",
            ]
        ),
        // ── Cross-runtime parity (Phase 8J) ──────────────────────
        // Spawns the Rust `fantastic` binary as a subprocess +
        // fires identical verb payloads at both kernels; diffs the
        // JSON replies. Skips when RUST_KERNEL_BIN env var is unset.
        .testTarget(
            name: "FantasticParityTests",
            dependencies: ["FantasticKernel", "FantasticJSON", "FantasticKernelStartup"]
        ),

        // ── CLI executable (Phase 7) ─────────────────────────────
        .executableTarget(
            name: "Fantastic",
            dependencies: [
                "FantasticKernelStartup", "FantasticKernel", "FantasticJSON",
            ]
        ),

        .testTarget(
            name: "FantasticBundlesTests",
            dependencies: [
                "FantasticKernel", "FantasticJSON",
                "FantasticFile", "FantasticProxyAgent", "FantasticTools",
                "FantasticHtmlAgent", "FantasticGlAgent", "FantasticScheduler",
                "FantasticCanvasBackend", "FantasticCanvasWebapp",
                "FantasticAiChatWebapp", "FantasticTerminalWebapp",
                "FantasticTelemetryPane", "FantasticCliBundle",
                "FantasticKernelBridge", "FantasticWeb",
            ]
        ),
    ]
)
