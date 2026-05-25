// swift-tools-version:6.0
//
// FantasticKernelFull — desktop / unsandboxed tier of the kernel as
// a Swift Package.
//
// **Backend switched from Rust XCFramework → native Swift kernel
// (`../../../swift`).** Same migration as `FantasticKernelEmbedded`,
// but macOS-only (this product never built iOS slices; the Pro tier
// is Developer ID + unsandboxed by definition).
//
// The native Swift kernel handles the Pro tier by enabling the
// `#if os(macOS)` paths inside `FantasticLocalRunner` and
// `FantasticPythonRuntime` automatically. `FantasticSshRunner` +
// `FantasticTerminalBackend` join the Pro tier as their Swift ports
// land in phases 8F + 8G.
//
// Use this from FantasticPro (macOS, Developer ID, unsandboxed).
// There are still no iOS slices; targeting iOS from this product is
// a build-time error by design.
//
// Lite uses the sister package `FantasticKernelEmbedded`.
//
// Consume from project.yml:
//   packages:
//     FantasticKernelFull:
//       path: ../../fantastic_canvas/rust/packaging/FantasticKernelFull
//   targets:
//     FantasticPro:
//       dependencies:
//         - package: FantasticKernelFull
//           product: FantasticKernelFull

import PackageDescription

let package = Package(
    name: "FantasticKernelFull",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .library(
            name: "FantasticKernelFull",
            targets: ["FantasticKernelFull"]
        )
    ],
    dependencies: [
        .package(path: "../../../swift")
    ],
    targets: [
        .target(
            name: "FantasticKernelFull",
            dependencies: [
                .product(name: "FantasticKernelStartup", package: "swift"),
                .product(name: "FantasticKernel", package: "swift"),
                .product(name: "FantasticJSON", package: "swift"),
            ],
            path: "Sources/FantasticKernelFull"
        )
    ]
)
