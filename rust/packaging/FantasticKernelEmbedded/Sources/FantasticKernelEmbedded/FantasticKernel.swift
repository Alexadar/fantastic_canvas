// FantasticKernelEmbedded — re-exports the native Swift kernel
// under the same module name the Apple app already imports.
//
// Backend swap: was a UniFFI XCFramework wrapper; now imports the
// Swift kernel directly. Consumers see the same symbols:
//
//     import FantasticKernelEmbedded
//
//     let kernel = try await startKernelInMemory(portHint: 0)
//     let port = kernel.httpPort()
//     defer { kernel.shutdown() }
//
//     class MyHost: ProxyAgent { ... }
//     try kernel.registerProxyAgent(agentId: "my_agent", host: MyHost())
//
// Migration note: prior versions of this package wrapped a Rust
// XCFramework built by `rust/scripts/build-xcframework-embedded.sh`.
// That script still works and the Rust kernel keeps building, but
// nothing in this Apple-platform Swift Package links it any more.

@_exported import FantasticJSON
@_exported import FantasticKernel
@_exported import FantasticKernelStartup
@_exported import FantasticProxyAgent
@_exported import FantasticTools

import Foundation

/// Convenience namespace + version constant. Actual API surface
/// lives in `FantasticKernel` and `FantasticKernelStartup`,
/// re-exported above.
public enum FantasticKernelEmbeddedInfo {
    /// Library version. Bumped alongside the Swift package's
    /// version. Distinct from the Rust `Cargo.toml` version because
    /// the implementations are now independent.
    public static let version = "0.2.0-swift"

    /// True when this binary is backed by the native Swift kernel
    /// (always true from v0.2.0 onward). Pre-0.2.0 versions wrapped
    /// the Rust XCFramework.
    public static let isSwiftNative = true
}
