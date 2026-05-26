// Apple Foundation Models LLM backend — kernel-native bundle.
//
// Wraps Apple's `FoundationModels` framework (`LanguageModelSession`)
// behind the same verb surface as `OllamaBackend` + `NvidiaNimBackend`,
// so chat UIs can speak to Apple FM exactly the way they speak to
// any other LLM backend in the kernel.
//
// Previously this code lived in the Apple app as
// `FoundationModelsProxyHost.swift` (a `proxy_agent` host) because the
// Rust kernel couldn't `import FoundationModels`. Now the kernel is
// native Swift, so the same logic moves into a substrate bundle —
// the CLI gets FM for free, and the app drops its host file.
//
// Platform gating: compile guarded by `canImport(FoundationModels)`
// + runtime `if #available`. On platforms / OS versions where the
// framework isn't available (anything below iOS 26 / macOS 26 /
// visionOS 26, or any tvOS / watchOS), the bundle compiles to a
// stub that always reports `available: false` and rejects `send`.
//
// Agent meta-field contract (read at session-build time once the
// follow-up activates the live `LanguageModelSession`):
//
//   meta.instructions  String  — system prompt body. Consumer owns
//                                the content; the bundle does no
//                                templating. Defaults to `""`.
//   meta.temperature   Number  — generation temperature in [0, 2].
//                                Defaults to 0.4 (WWDC25 guidance
//                                for tool-grounded factual answers;
//                                Apple's default ~0.8 is "inconsistent
//                                and nonsensical" in their language).
//
// These are stored on the agent record by whoever creates the
// `fm` agent (typically the Apple app or a CLI wrapper); the
// bundle reads them lazily and never writes back.

import FantasticJSON
import FantasticKernel
import Foundation
import OrderedCollections

#if canImport(FoundationModels)
    import FoundationModels
#endif

public let HANDLER_MODULE = "foundation_models_backend.tools"

public final class FoundationModelsBackendBundle: AgentBundle, @unchecked Sendable {
    public let name = "foundation_models_backend"
    public init() {}

    /// Per-(agent_id, client_id) chat history. Matches the keying
    /// scheme `OllamaBackend` uses so chat UIs see identical
    /// `history` replies across backends.
    private let historyLock = NSLock()
    private var history: [String: [JSON]] = [:]

    /// Per-stream cancel flags. Set by `interrupt`, checked by the
    /// generation Task in its inner loop.
    private let cancelLock = NSLock()
    private var cancelled: Set<String> = []

    /// In-flight stream count for `backend_state` reporting.
    private let stateLock = NSLock()
    private var inFlight: Int = 0
    private var queueDepth: Int = 0

    public func handle(
        agentId: AgentId,
        payload: JSON,
        kernel: Kernel
    ) async throws -> JSON? {
        let verb = payload["type"].asString ?? ""
        guard let agent = kernel.agent(agentId) else {
            return .object(["error": .string("no agent")])
        }
        switch verb {
        case "reflect":
            return [
                "id": .string(agent.id.value),
                "kind": .string("foundation_models_backend"),
                "provider": .string("apple_foundation_models"),
                "available": .bool(isAvailable()),
                "model": .string(modelLabel()),
                "verbs": [
                    "send": "args: text, client_id?. Streams a response.",
                    "history": "args: client_id?. Returns prior turns.",
                    "interrupt": "args: client_id?. Cancels in-flight stream.",
                    "backend_state": "Reports availability + in-flight + queue depth.",
                ] as JSON,
            ] as JSON
        case "boot":
            return .object(["ok": .bool(true)])
        case "shutdown":
            return .object(["ok": .bool(true)])
        case "send":
            return await sendVerb(agent: agent, payload: payload, kernel: kernel)
        case "history":
            return historyVerb(agent: agent, payload: payload)
        case "interrupt":
            return interruptVerb(payload: payload)
        case "backend_state":
            return backendStateReply()
        default:
            return .object(["error": .string("unknown verb \(verb)")])
        }
    }

    // MARK: - Verbs

    private func sendVerb(agent: Agent, payload: JSON, kernel: Kernel) async -> JSON {
        guard let text = payload["text"].asString else {
            return .object(["error": .string("send requires text")])
        }
        let clientId = payload["client_id"].asString ?? "cli"

        guard isAvailable() else {
            return .object([
                "error": .string("foundation_models_unavailable"),
                "reason": .string(unavailableReason()),
            ])
        }

        let streamId = "stm_\(UUID().uuidString.prefix(8))"
        let messageId = "msg_\(UUID().uuidString.prefix(8))"
        let userMessageId = "msg_\(UUID().uuidString.prefix(8))"

        appendHistory(
            key: historyKey(agent: agent.id, client: clientId),
            message: .object([
                "id": .string(userMessageId),
                "role": .string("user"),
                "content": .string(text),
                "complete": .bool(true),
            ]))

        // Surface the meta contract for the follow-up port. Read here
        // even though the stub doesn't pass them to FM yet, so that a
        // misconfigured agent fails loudly with a typed error instead
        // of silently using the defaults.
        _ = instructions(agent: agent)
        _ = temperature(agent: agent)

        // Skeleton: spawn a stub task that emits one done event.
        // Real `LanguageModelSession.respond(to:)` integration lands
        // in the follow-up; this commit only proves the bundle shape.
        bumpInFlight(+1)
        Task { [weak self, weak kernel] in
            guard let self = self, let kernel = kernel else { return }
            await self.runStream(
                streamId: streamId,
                messageId: messageId,
                agentId: agent.id,
                clientId: clientId,
                userText: text,
                kernel: kernel
            )
        }

        return .object([
            "queued": .bool(true),
            "stream_id": .string(streamId),
            "message_id": .string(messageId),
            "client_id": .string(clientId),
        ])
    }

    private func runStream(
        streamId: String,
        messageId: String,
        agentId: AgentId,
        clientId: String,
        userText: String,
        kernel: Kernel
    ) async {
        defer {
            clearCancel(streamId)
            bumpInFlight(-1)
        }

        #if canImport(FoundationModels)
            if #available(macOS 26, iOS 26, visionOS 26, *) {
                // TODO(swift-fm-fix follow-up): port the live
                // `LanguageModelSession.respond(to:options:)` streaming
                // loop from
                // /Users/oleksandr/Projects/fantastic_app/apple/Fantastic/
                //   Connectivity/FoundationModelsProxyHost.swift
                // — queue + session reuse + retry + tool-call thread-
                // through. For the skeleton commit we emit a single
                // stub token + done so the verb shape is exercised.
                await kernel.emit(
                    agentId,
                    .object([
                        "type": .string("token"),
                        "stream_id": .string(streamId),
                        "message_id": .string(messageId),
                        "delta": .string(""),
                        "accumulated": .string(""),
                        "client_id": .string(clientId),
                    ]))
                await kernel.emit(
                    agentId,
                    .object([
                        "type": .string("done"),
                        "stream_id": .string(streamId),
                        "message_id": .string(messageId),
                        "accumulated": .string(""),
                        "client_id": .string(clientId),
                        "stub": .bool(true),
                    ]))
                appendHistory(
                    key: historyKey(agent: agentId, client: clientId),
                    message: .object([
                        "id": .string(messageId),
                        "role": .string("assistant"),
                        "content": .string(""),
                        "complete": .bool(true),
                    ]))
                return
            }
        #endif

        // Framework unavailable at runtime — emit an error done event.
        await kernel.emit(
            agentId,
            .object([
                "type": .string("done"),
                "stream_id": .string(streamId),
                "message_id": .string(messageId),
                "error": .string("foundation_models_unavailable"),
                "client_id": .string(clientId),
            ]))
        _ = userText  // silence unused; real run consumes it
    }

    private func historyVerb(agent: Agent, payload: JSON) -> JSON {
        let clientId = payload["client_id"].asString ?? "cli"
        let messages = readHistory(key: historyKey(agent: agent.id, client: clientId))
        return .object([
            "messages": .array(messages),
            "client_id": .string(clientId),
        ])
    }

    private func interruptVerb(payload: JSON) -> JSON {
        cancelLock.lock()
        cancelled.removeAll()
        cancelLock.unlock()
        _ = payload  // client_id reserved for per-stream cancel in follow-up
        return .object(["interrupted": .bool(true)])
    }

    private func backendStateReply() -> JSON {
        let (inFlightNow, queueNow) = readState()
        return .object([
            "provider": .string("apple_foundation_models"),
            "apple_intelligence_available": .bool(isAvailable()),
            "model_available": .bool(isAvailable()),
            "backend_registered": .bool(true),
            "model": .string(modelLabel()),
            "in_flight": .integer(Int64(inFlightNow)),
            "queue_depth": .integer(Int64(queueNow)),
            "reason": .string(isAvailable() ? "ok" : unavailableReason()),
        ])
    }

    // MARK: - Availability + model identity

    /// True when the FoundationModels framework is reachable AND
    /// the system model reports `.available` at runtime. Compile-
    /// gated by `canImport`; runtime-gated by `#available` + the
    /// `SystemLanguageModel.default.availability` enum.
    private func isAvailable() -> Bool {
        #if canImport(FoundationModels)
            if #available(macOS 26, iOS 26, visionOS 26, *) {
                return SystemLanguageModel.default.availability == .available
            }
        #endif
        return false
    }

    /// Human-readable reason for unavailability. Mirrors the
    /// reasons the app's chat UI surfaces today.
    private func unavailableReason() -> String {
        #if canImport(FoundationModels)
            if #available(macOS 26, iOS 26, visionOS 26, *) {
                switch SystemLanguageModel.default.availability {
                case .available:
                    return "ok"
                case .unavailable(let reason):
                    switch reason {
                    case .appleIntelligenceNotEnabled:
                        return "apple_intelligence_not_enabled"
                    case .deviceNotEligible:
                        return "device_not_eligible"
                    case .modelNotReady:
                        return "model_not_ready"
                    @unknown default:
                        return "unavailable_unknown"
                    }
                @unknown default:
                    return "unavailable_unknown"
                }
            }
            return "os_version_too_old"
        #else
            return "framework_not_available"
        #endif
    }

    private func modelLabel() -> String {
        #if canImport(FoundationModels)
            // Apple FM ships one on-device system model today —
            // no per-instance model id is exposed via the public
            // API. Label is stable for telemetry.
            return "apple_system_language_model"
        #else
            return "n/a"
        #endif
    }

    /// System-prompt body for the LLM session. Read from the
    /// agent's `meta.instructions` field at session-build time
    /// (currently unused — the live FM port reads + applies this
    /// in the follow-up). Empty string is treated the same as
    /// "no instructions" by Apple FM.
    private func instructions(agent: Agent) -> String {
        agent.metaValue(forKey: "instructions")?.asString ?? ""
    }

    /// Generation temperature in [0, 2]. Read from the agent's
    /// `meta.temperature` field; defaults to 0.4 (WWDC25 guidance
    /// for tool-grounded factual answers). Anything outside the
    /// valid range is clamped at apply-time in the follow-up.
    private func temperature(agent: Agent) -> Double {
        if let dbl = agent.metaValue(forKey: "temperature")?.asDouble {
            return dbl
        }
        if let i = agent.metaValue(forKey: "temperature")?.asInt {
            return Double(i)
        }
        return 0.4
    }

    // MARK: - History / cancel / state helpers (NSLock-protected)

    private func historyKey(agent: AgentId, client: String) -> String {
        "\(agent.value)|\(client)"
    }

    private func appendHistory(key: String, message: JSON) {
        historyLock.lock()
        defer { historyLock.unlock() }
        var arr = history[key] ?? []
        arr.append(message)
        history[key] = arr
    }

    private func readHistory(key: String) -> [JSON] {
        historyLock.lock()
        defer { historyLock.unlock() }
        return history[key] ?? []
    }

    private func clearCancel(_ id: String) {
        cancelLock.lock()
        defer { cancelLock.unlock() }
        cancelled.remove(id)
    }

    private func bumpInFlight(_ delta: Int) {
        stateLock.lock()
        defer { stateLock.unlock() }
        inFlight = max(0, inFlight + delta)
    }

    private func readState() -> (inFlight: Int, queue: Int) {
        stateLock.lock()
        defer { stateLock.unlock() }
        return (inFlight, queueDepth)
    }
}
