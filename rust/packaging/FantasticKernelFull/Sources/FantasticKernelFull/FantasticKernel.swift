// FantasticKernelFull — re-exports the native Swift kernel under the
// same module name the FantasticPro app target already imports.
//
// Backend swap: was a UniFFI XCFramework wrapper; now imports the
// Swift kernel directly. macOS-only — the kernel's Pro-tier bundles
// (local_runner, python_runtime, future ssh_runner +
// terminal_backend) live behind `#if os(macOS)` in the Swift
// workspace and compile in automatically here.
//
//     import FantasticKernelFull
//
//     let kernel = try await startKernel(
//         workdir: workspaceURL.path,
//         portHint: 0
//     )

@_exported import FantasticJSON
@_exported import FantasticKernel
@_exported import FantasticKernelStartup

import Foundation

public enum FantasticKernelFullInfo {
    public static let version = "0.2.0-swift"
    public static let isSwiftNative = true
}
