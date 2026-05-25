// swift-tools-version:6.0
//
// FantasticKernelEmbedded — sandboxed tier of the kernel as a Swift
// Package.
//
// **Backend switched from Rust XCFramework → native Swift kernel
// (`../../../swift`).** The Apple app's import lines + call sites are
// unchanged; the implementation underneath now compiles Swift directly
// instead of bridging through UniFFI to a Rust static lib.
//
// The Rust XCFramework is still built by
// `rust/scripts/build-xcframework-embedded.sh` so Rust keeps emitting
// Swift bindings for non-Apple-app consumers (cross-runtime testing,
// external integrators), but no path here links it.
//
// Use this from FantasticLite (multi-platform: iOS, iPadOS, macOS Lite).
// The embedded tier compile-time excludes subprocess bundles via the
// Swift kernel's `#if os(macOS)` gates inside `FantasticLocalRunner`
// and `FantasticPythonRuntime`.
//
// Pro Mac uses the sister package `FantasticKernelFull`.
//
// Consume from project.yml:
//   packages:
//     FantasticKernelEmbedded:
//       path: ../../fantastic_canvas/rust/packaging/FantasticKernelEmbedded
//   targets:
//     FantasticLite:
//       dependencies:
//         - package: FantasticKernelEmbedded
//           product: FantasticKernelEmbedded

import PackageDescription

let package = Package(
    name: "FantasticKernelEmbedded",
    platforms: [
        .macOS(.v14),
        .iOS(.v17),
        .tvOS(.v17),
        .visionOS(.v1),
        .watchOS(.v10),
    ],
    products: [
        .library(
            name: "FantasticKernelEmbedded",
            targets: ["FantasticKernelEmbedded"]
        )
    ],
    dependencies: [
        // The native Swift kernel workspace, two directories up.
        .package(path: "../../../swift")
    ],
    targets: [
        // Wrapper target — `@_exported import`s the Swift kernel's
        // public surface so app-side `import FantasticKernelEmbedded`
        // continues to find `startKernelInMemory`, `startKernel`,
        // `Kernel`, `ProxyAgent`, etc. without code changes.
        .target(
            name: "FantasticKernelEmbedded",
            dependencies: [
                .product(name: "FantasticKernelStartup", package: "swift"),
                .product(name: "FantasticKernel", package: "swift"),
                .product(name: "FantasticJSON", package: "swift"),
            ],
            path: "Sources/FantasticKernelEmbedded"
        )
    ]
)
