// Cross-kernel bridge bundle.
//
// Mirrors Rust's `fantastic-kernel-bridge::KernelBridgeBundle`.
// Lets one kernel address agents living in another kernel via an
// in-memory channel, WebSocket, or HTTP transport. The Swift port
// ships the in-memory transport (used for cross-runtime tests + the
// app's brain ↔ workspace kernel pairing). WS/HTTP transports land
// with Phase 4's Hummingbird integration.

import FantasticJSON
import FantasticKernel
import Foundation

public let HANDLER_MODULE = "kernel_bridge.tools"

/// In-memory bridge — the simplest transport. Both kernels live in
/// the same process; verb forwarding is a direct async call.
public actor InMemoryBridge {
    private weak var remoteKernel: Kernel?

    public init(remote: Kernel) {
        self.remoteKernel = remote
    }

    public func forward(target: AgentId, payload: JSON) async -> JSON {
        guard let remote = remoteKernel else {
            return .object(["error": .string("remote kernel gone")])
        }
        return await remote.send(target, payload)
    }
}

public final class KernelBridgeBundle: AgentBundle, @unchecked Sendable {
    public let name = "kernel_bridge"
    private let lock = NSLock()
    private var bridges: [AgentId: InMemoryBridge] = [:]

    public init() {}

    /// Attach an in-memory bridge for `agentId` pointing at `remote`.
    /// The app calls this after creating a `kernel_bridge.tools`
    /// agent in the local kernel.
    public func attachInMemory(agentId: AgentId, remote: Kernel) {
        lock.lock()
        defer { lock.unlock() }
        bridges[agentId] = InMemoryBridge(remote: remote)
    }

    /// Sync lookup helper — keeps the NSLock outside any async scope.
    private func bridgeFor(_ agentId: AgentId) -> InMemoryBridge? {
        lock.lock()
        defer { lock.unlock() }
        return bridges[agentId]
    }

    public func handle(
        agentId: AgentId,
        payload: JSON,
        kernel: Kernel
    ) async throws -> JSON? {
        let verb = payload["type"].asString ?? ""
        switch verb {
        case "reflect":
            return [
                "id": .string(agentId.value),
                "kind": .string("kernel_bridge"),
                "sentence": .string("Cross-kernel transport bundle (in-memory only in Phase 3)."),
                "verbs": [
                    "forward":
                        "args: target_id, payload. Forwards to the attached remote kernel."
                ] as JSON,
            ] as JSON
        case "boot", "shutdown":
            return .object(["ok": .bool(true)])
        case "forward":
            guard let targetStr = payload["target_id"].asString else {
                return .object(["error": .string("forward requires target_id")])
            }
            let bridge = bridgeFor(agentId)
            guard let bridge = bridge else {
                return .object([
                    "error": .string("no bridge attached"),
                    "reason": .string("not_attached"),
                ])
            }
            return await bridge.forward(
                target: AgentId(targetStr),
                payload: payload["payload"])
        default:
            return .object(["error": .string("unknown verb \(verb)")])
        }
    }
}
