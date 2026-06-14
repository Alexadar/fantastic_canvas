// AIBackend — the shared reflect-driven LLM-agent machinery behind the
// `AIProvider` seam. The ollama / NIM / Apple-FM bundles supply only
// their `AIProvider` impl + an `AIBackendConfig`, and dispatch every
// verb through the `handle` method here.
//
// Extracted from the three (formerly duplicated) Swift backends. The
// shared layer owns: per-(agent, client_id) chat history, the
// epoch-bump cancellation state, the verb bodies (reflect / boot /
// shutdown / send / history / interrupt / backend_state), the spawned
// streaming task, and the token / done event emission. The providers
// own only the upstream wire (NDJSON, SSE+429+Bearer, on-device
// session).
//
// Wire contract (byte-identical to the Python reference, enforced by
// FantasticParityTests):
//
//   send → {queued, stream_id, message_id, client_id}
//   token event → {type:token, stream_id, message_id, delta,
//                  accumulated, client_id}
//   done  event → {type:done, stream_id, message_id, accumulated?,
//                  client_id, error?}
//   history → {messages, client_id}
//   interrupt → {interrupted:true}
//
// This module MUST NOT import FoundationModels (or any provider SDK).

import FantasticJSON
import FantasticKernel
import Foundation
import OrderedCollections

/// Construct the shared backend machinery for one bundle. Returns an
/// `AIBackend` the bundle's `handle` delegates straight to. Mirrors
/// Rust's `buildAIBackend` / the Python `ai_core` factory.
public func buildAIBackend(_ config: AIBackendConfig) -> AIBackend {
    AIBackend(config: config)
}

public final class AIBackend: @unchecked Sendable {
    public let config: AIBackendConfig

    /// Per-`send` wall-clock ceiling. A generation that streams past this
    /// is force-stopped with a terminal `done{error:"send: timeout …"}`.
    /// Bounds runaway tool loops / a stuck provider. Mirrors Python
    /// `SEND_TIMEOUT` / Rust `SEND_TIMEOUT_SECS` (default 180s; the env
    /// override `FANTASTIC_AI_SEND_TIMEOUT` is read once at init).
    public static let defaultSendTimeoutSeconds: Double = 180
    private let sendTimeoutSeconds: Double = {
        if let raw = ProcessInfo.processInfo.environment["FANTASTIC_AI_SEND_TIMEOUT"],
            let v = Double(raw), v > 0
        {
            return v
        }
        return AIBackend.defaultSendTimeoutSeconds
    }()

    /// Cancellation state — epoch-bump pattern (lifted verbatim from
    /// the FM backend, which had the most robust version). `interrupt`
    /// bumps `interruptEpoch`; every stream records the epoch it
    /// started under and polls `isStreamCancelled` each tick. A stream
    /// is cancelled iff its `startedAt` epoch is older than the current
    /// epoch OR its id is explicitly in `cancelledStreams`. Epoch
    /// counters are race-free against staggered stream-death and don't
    /// bleed into post-interrupt sends.
    private let cancelLock = NSLock()
    private var interruptEpoch: UInt64 = 0
    private var cancelledStreams: Set<String> = []

    /// In-flight stream count for `backend_state` reporting.
    private let stateLock = NSLock()
    private var inFlight: Int = 0

    /// Lazy per-agent "menu of capabilities" cache (id → reflected
    /// peers). `nil`/absent means "rebuild on the next assemble". The
    /// `refresh_menu` verb + each tool batch invalidate it. Mirrors the
    /// Rust `BackendState.menu` / Python `_menu_cache`.
    private let menuLock = NSLock()
    private var menuCache: [String: [JSON]] = [:]

    init(config: AIBackendConfig) {
        self.config = config
    }

    // MARK: - Verb dispatch

    /// Single entry point — the bundle's `handle` forwards here.
    public func handle(
        agentId: AgentId,
        payload: JSON,
        kernel: Kernel
    ) async -> JSON? {
        let verb = payload["type"].asString ?? ""
        guard let agent = kernel.agent(agentId) else {
            return .object(["error": .string("no agent")])
        }
        switch verb {
        case "reflect":
            return reflectReply(agent: agent)
        case "boot":
            return .object(["ok": .bool(true)])
        case "shutdown":
            return .object(["ok": .bool(true)])
        case "send":
            return await sendVerb(agent: agent, payload: payload, kernel: kernel)
        case "history":
            return await historyVerb(agent: agent, payload: payload, kernel: kernel)
        case "interrupt":
            return interruptVerb(payload: payload)
        case "refresh_menu":
            invalidateMenu(agentId)
            return .object(["refreshed": .bool(true)])
        case "backend_state":
            return backendStateReply(agent: agent)
        default:
            return .object(["error": .string("unknown verb \(verb)")])
        }
    }

    // MARK: - reflect / backend_state

    private func reflectReply(agent: Agent) -> JSON {
        var fields: OrderedDictionary<String, JSON> = [:]
        fields["id"] = .string(agent.id.value)
        fields["sentence"] = .string(config.sentence)
        fields["kind"] = .string(config.kind)
        fields["provider"] = .string(config.provider)
        for (k, v) in config.reflectExtra(agent) {
            fields[k] = v
        }
        fields["verbs"] = config.verbs
        return .object(fields)
    }

    private func backendStateReply(agent: Agent) -> JSON {
        var fields: OrderedDictionary<String, JSON> = [:]
        fields["provider"] = .string(config.provider)
        for (k, v) in config.backendStateExtra(agent) {
            fields[k] = v
        }
        return .object(fields)
    }

    // MARK: - send

    private func sendVerb(agent: Agent, payload: JSON, kernel: Kernel) async -> JSON {
        guard let text = payload["text"].asString else {
            return .object(["error": .string("send requires text")])
        }
        let clientId = payload["client_id"].asString ?? "cli"

        // Build the provider FIRST — backends that must refuse before
        // touching history (NIM no-api_key, FM unavailable) return their
        // exact refusal body here, preserving wire byte-identity.
        let result = await config.makeProvider(agent, clientId, kernel)
        let provider: any AIProvider
        switch result {
        case .refused(let body):
            return body
        case .provider(let p):
            provider = p
        }

        let streamId = "stm_\(UUID().uuidString.prefix(8))"
        let messageId = "msg_\(UUID().uuidString.prefix(8))"
        let userMessageId = "msg_\(UUID().uuidString.prefix(8))"

        // Load the persisted chat through the bound file_bridge (empty if
        // none wired / first turn), then persist it WITH the new user turn
        // immediately so the turn survives even if the stream dies. The
        // user row carries `id` only for stateless backends (FM bubble
        // identity); ollama/NIM don't.
        let prior = await loadHistory(agent: agent, client: clientId, kernel: kernel)
        let userTurnRow = userTurn(id: userMessageId, text: text)
        let persistBase = prior + [userTurnRow]
        await saveHistory(agent: agent, client: clientId, kernel: kernel, rows: persistBase)

        // The single universal `send` tool — reaches every agent + verb
        // (matches Python `[SEND_TOOL]` / Rust `vec![send_tool_def()]`).
        // No `list_for_llm` registry: capability is discovered via the
        // assembled menu + reflect, dispatched through this one tool.
        let tools = [sendToolDef()]

        // Stateless backends (FM) do NOT feed prior history back as model
        // context (it stays UI-only); the others do.
        let modelHistory = config.stateless ? [] : prior

        bumpInFlight(+1)
        Task { [weak self, weak kernel] in
            guard let self = self, let kernel = kernel else { return }
            await self.runStream(
                provider: provider,
                streamId: streamId,
                messageId: messageId,
                agent: agent,
                clientId: clientId,
                modelHistory: modelHistory,
                persistBase: persistBase,
                userText: text,
                tools: tools,
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
        provider: any AIProvider,
        streamId: String,
        messageId: String,
        agent: Agent,
        clientId: String,
        modelHistory: [JSON],
        persistBase: [JSON],
        userText: String,
        tools: [JSON],
        kernel: Kernel
    ) async {
        let agentId = agent.id
        defer {
            clearStreamCancel(streamId)
            bumpInFlight(-1)
        }

        // Snapshot the cancel epoch before the first token so interrupts
        // that fire mid-stream are detected via `startedAt < epoch`.
        let startedAtEpoch = currentEpoch()
        let deadline = Date().addingTimeInterval(sendTimeoutSeconds)

        // Rebuild the system block every turn from the live substrate
        // (primer + self-reflect + agent menu + send how-to + per-backend
        // extra). Prepended to prior history (empty when stateless) and
        // the new user turn. The system block is NOT persisted — only the
        // user/assistant/tool turns flow into history.
        let systemContent = await assembleSystemPrompt(agent: agent, kernel: kernel)
        var messages: [JSON] = [
            .object(["role": .string("system"), "content": .string(systemContent)])
        ]
        messages.append(contentsOf: modelHistory)
        messages.append(
            .object(["role": .string("user"), "content": .string(userText)]))

        // The agentic loop: stream a pass, dispatch any tool-calls back
        // through the kernel, feed the results in, repeat until the model
        // stops emitting tools. FM yields no tool-calls (Apple runs them
        // inside the session), so it runs exactly one pass. Mirrors Rust
        // `run_generation` / Python `_run`.
        var accumulated = ""  // generation-wide, for the UI token stream
        var lastText = ""  // current pass text → the final assistant turn
        var newTurns: [JSON] = []  // assistant/tool turns to persist at the end
        var cancelled = false

        loop: while true {
            var passText = ""
            var passToolCalls: [JSON] = []
            do {
                let stream = provider.chat(messages: messages, tools: tools)
                for try await chunk in stream {
                    if Date() > deadline {
                        await provider.stop()
                        await emitDone(
                            kernel: kernel, agentId: agentId,
                            streamId: streamId, messageId: messageId,
                            clientId: clientId, accumulated: accumulated,
                            error: "send: timeout after \(Int(sendTimeoutSeconds))s")
                        return
                    }
                    if isStreamCancelled(streamId: streamId, startedAt: startedAtEpoch) {
                        await provider.stop()
                        if config.emitInterruptedError {
                            // FM shape: terminal `done{error:"interrupted"}`,
                            // partial turn NOT persisted.
                            await emitDone(
                                kernel: kernel, agentId: agentId,
                                streamId: streamId, messageId: messageId,
                                clientId: clientId, accumulated: accumulated,
                                error: "interrupted")
                            return
                        }
                        cancelled = true
                        break
                    }
                    switch chunk {
                    case .token(let delta):
                        accumulated += delta
                        passText += delta
                        await kernel.emit(
                            agentId,
                            .object([
                                "type": .string("token"),
                                "stream_id": .string(streamId),
                                "message_id": .string(messageId),
                                "delta": .string(delta),
                                "accumulated": .string(accumulated),
                                "client_id": .string(clientId),
                            ]))
                    case .toolCall(let call):
                        passToolCalls.append(call)
                    }
                }
            } catch {
                await emitDone(
                    kernel: kernel, agentId: agentId,
                    streamId: streamId, messageId: messageId,
                    clientId: clientId, accumulated: accumulated,
                    error: "\(error)")
                return
            }
            lastText = passText

            // No tools (or interrupted) → this pass is the final answer.
            if passToolCalls.isEmpty || cancelled { break loop }

            // Record the assistant turn carrying its tool-calls (the
            // provider's own OpenAI-shaped chunks, echoed verbatim so the
            // next pass sees a well-formed conversation), then dispatch
            // each call through the kernel and feed the replies back.
            let assistantTurnWithTools: JSON = .object([
                "role": .string("assistant"),
                "content": .string(passText),
                "tool_calls": .array(passToolCalls),
            ])
            messages.append(assistantTurnWithTools)
            newTurns.append(assistantTurnWithTools)

            let results = await dispatchToolCalls(
                passToolCalls, parallel: config.parallelTools, kernel: kernel)
            messages.append(contentsOf: results)
            newTurns.append(contentsOf: results)

            // The population may have changed (a tool created/deleted an
            // agent) — rebuild the menu before the next pass.
            invalidateMenu(agentId)
        }

        // Persist the full chat: base (prior + user turn, already saved at
        // send time) + the intermediate tool turns + the final assistant
        // turn. One write of the whole conversation (matches Rust/Python
        // `save_history`). The error / FM-interrupt / timeout paths return
        // earlier and leave the send-time base (with just the user turn)
        // as the persisted record.
        let finalRows =
            persistBase + newTurns
            + [assistantTurn(id: messageId, content: lastText, toolCalls: [])]
        await saveHistory(agent: agent, client: clientId, kernel: kernel, rows: finalRows)

        await emitDone(
            kernel: kernel, agentId: agentId,
            streamId: streamId, messageId: messageId,
            clientId: clientId, accumulated: accumulated, error: nil)
    }

    // MARK: - prompt assembly + tool dispatch

    /// Rebuild the system prompt from the live substrate: lean primer
    /// (id-index of the tree + bundle catalog), the agent's own
    /// self-reflect, the lazy menu of peers, the universal `send` how-to,
    /// and any per-backend extra (FM's always-inject memory). Mirrors
    /// Rust `assemble_messages` / Python `_assemble`.
    func assembleSystemPrompt(agent: Agent, kernel: Kernel) async -> String {
        let selfId = agent.id
        let primer = await kernel.send(
            AgentId("core"),
            .object([
                "type": .string("reflect"),
                "tree": .string("ids"),
                "bundles": .string("ids"),
            ]))
        let me = await kernel.send(
            selfId, .object(["type": .string("reflect"), "tree": .string("none")]))

        // Lazy menu: rebuild only on a cache miss.
        let menu: [JSON]
        if let cached = cachedMenu(selfId.value) {
            menu = cached
        } else {
            let built = await buildMenu(selfId: selfId, kernel: kernel)
            storeMenu(selfId.value, built)
            menu = built
        }

        var blocks: [String] = [
            renderReflect(primer),
            "You are `\(selfId.value)`. " + renderReflect(me),
            renderMenu(menu),
            SEND_HOWTO,
        ]
        let extra = await config.systemPromptExtra(agent, kernel)
        if !extra.isEmpty { blocks.append(extra) }
        return blocks.joined(separator: "\n\n")
    }

    /// Drop an agent's cached menu so the next assemble rebuilds it.
    private func invalidateMenu(_ id: AgentId) {
        menuLock.lock()
        defer { menuLock.unlock() }
        menuCache[id.value] = nil
    }

    /// Synchronous menu-cache accessors (NSLock can't span `await`).
    private func cachedMenu(_ id: String) -> [JSON]? {
        menuLock.lock()
        defer { menuLock.unlock() }
        return menuCache[id]
    }

    private func storeMenu(_ id: String, _ menu: [JSON]) {
        menuLock.lock()
        defer { menuLock.unlock() }
        menuCache[id] = menu
    }

    /// Dispatch one provider tool-call (always the universal `send`)
    /// through the kernel and shape the `role:tool` reply message. The
    /// call's `function.arguments` may be a JSON string (OpenAI/NIM) or a
    /// parsed object (ollama) — both resolve to `{target_id, payload}`.
    private func dispatchToolCall(_ call: JSON, kernel: Kernel) async -> JSON {
        let id = call["id"].asString ?? ""
        let fn = call["function"]
        let name = fn["name"].asString ?? "send"
        let rawArgs = fn["arguments"]
        var args: JSON = .object([:])
        if let s = rawArgs.asString {
            args = (try? JSON.parse(s)) ?? .object([:])
        } else if rawArgs.asObject != nil {
            args = rawArgs
        }
        let target = args["target_id"].asString ?? ""
        let payload = args["payload"]
        let reply: JSON
        if target.isEmpty {
            reply = .object(["error": .string("empty target_id")])
        } else {
            reply = await kernel.send(AgentId(target), payload)
        }
        return .object([
            "role": .string("tool"),
            "tool_call_id": .string(id),
            "name": .string(name),
            "content": .string(reply.serialize()),
        ])
    }

    /// Dispatch a batch of tool-calls, preserving model-emitted order in
    /// the returned `role:tool` messages. Concurrent when `parallel`
    /// (ollama / FM), serial otherwise (NIM).
    private func dispatchToolCalls(
        _ calls: [JSON], parallel: Bool, kernel: Kernel
    ) async -> [JSON] {
        if !parallel {
            var out: [JSON] = []
            for c in calls {
                out.append(await dispatchToolCall(c, kernel: kernel))
            }
            return out
        }
        return await withTaskGroup(of: (Int, JSON).self) { group in
            for (i, c) in calls.enumerated() {
                group.addTask { (i, await self.dispatchToolCall(c, kernel: kernel)) }
            }
            var indexed: [(Int, JSON)] = []
            for await r in group { indexed.append(r) }
            return indexed.sorted { $0.0 < $1.0 }.map { $0.1 }
        }
    }

    /// Emit the terminal `done` event. On the error path, `accumulated`
    /// is included only when the backend historically did so (NIM).
    private func emitDone(
        kernel: Kernel,
        agentId: AgentId,
        streamId: String,
        messageId: String,
        clientId: String,
        accumulated: String,
        error: String?
    ) async {
        var event: OrderedDictionary<String, JSON> = [:]
        event["type"] = .string("done")
        event["stream_id"] = .string(streamId)
        event["message_id"] = .string(messageId)
        if error == nil || config.includeAccumulatedOnError {
            event["accumulated"] = .string(accumulated)
        }
        event["client_id"] = .string(clientId)
        if let error = error {
            event["error"] = .string(error)
        }
        await kernel.emit(agentId, .object(event))
    }

    // MARK: - history / interrupt

    private func historyVerb(agent: Agent, payload: JSON, kernel: Kernel) async -> JSON {
        let clientId = payload["client_id"].asString ?? "cli"
        let messages = await loadHistory(agent: agent, client: clientId, kernel: kernel)
        return .object([
            "messages": .array(messages),
            "client_id": .string(clientId),
        ])
    }

    private func interruptVerb(payload: JSON) -> JSON {
        cancelLock.lock()
        interruptEpoch &+= 1
        cancelLock.unlock()
        _ = payload  // client_id reserved for per-stream cancel later
        return .object(["interrupted": .bool(true)])
    }

    // MARK: - history row shapes

    private func userTurn(id: String, text: String) -> JSON {
        var row: OrderedDictionary<String, JSON> = [:]
        if config.stateless { row["id"] = .string(id) }
        row["role"] = .string("user")
        row["content"] = .string(text)
        row["complete"] = .bool(true)
        return .object(row)
    }

    private func assistantTurn(id: String, content: String, toolCalls: [JSON]) -> JSON {
        var row: OrderedDictionary<String, JSON> = [:]
        if config.stateless { row["id"] = .string(id) }
        row["role"] = .string("assistant")
        row["content"] = .string(content)
        row["complete"] = .bool(true)
        if config.persistToolCalls && !toolCalls.isEmpty {
            // Sort by id to match the prior NIM ordering exactly.
            let sorted = toolCalls.sorted { lhs, rhs in
                (lhs["id"].asString ?? "") < (rhs["id"].asString ?? "")
            }
            row["tool_calls"] = .array(sorted)
        }
        return .object(row)
    }

    // MARK: - history persistence (routed through file_bridge_id)

    /// The bound file_bridge agent id, if the operator (ollama / NIM) or
    /// the backend's own boot (FM) wired one. No id ⇒ no persistence
    /// (history stays empty across turns) — the canonical "no provider ⇒
    /// nothing persisted", NOT a fallback.
    private func fileBridgeId(_ agent: Agent) -> String? {
        agent.metaValue(forKey: "file_bridge_id")?.asString
    }

    /// Trim + sanitise a client id so it's safe as a filename suffix.
    /// Mirrors Rust `safe_client` / Python `_safe_client`.
    private func safeClient(_ clientId: String) -> String {
        let trimmed = clientId.trimmingCharacters(in: .whitespaces)
        let raw = trimmed.isEmpty ? "cli" : trimmed
        let mapped = raw.map { c -> Character in
            (c.isLetter || c.isNumber || c == "." || c == "_" || c == "-") ? c : "_"
        }
        let out = String(mapped.prefix(64))
        return out.isEmpty ? "cli" : out
    }

    /// Per-client chat thread, STORE-RELATIVE (`agents/<id>/…`) so wiring
    /// `file_bridge_id` to the `.fantastic` store lands the sidecar next
    /// to the agent's own record. Matches Rust/Python `chat_path`.
    private func chatPath(_ id: AgentId, _ client: String) -> String {
        "agents/\(id.value)/chat_\(safeClient(client)).json"
    }

    /// Load a client's persisted chat via the bound file_bridge. Empty on
    /// no provider / missing file / unparseable.
    private func loadHistory(agent: Agent, client: String, kernel: Kernel) async -> [JSON] {
        guard let fid = fileBridgeId(agent) else { return [] }
        let r = await kernel.send(
            AgentId(fid),
            .object(["type": .string("read"), "path": .string(chatPath(agent.id, client))]))
        guard let content = r["content"].asString,
            let parsed = try? JSON.parse(content),
            let arr = parsed.asArray
        else { return [] }
        return arr
    }

    /// Persist a client's full chat via the bound file_bridge. No-op when
    /// no provider is wired (matches Rust's ignore-on-unset).
    private func saveHistory(agent: Agent, client: String, kernel: Kernel, rows: [JSON]) async {
        guard let fid = fileBridgeId(agent) else { return }
        _ = await kernel.send(
            AgentId(fid),
            .object([
                "type": .string("write"),
                "path": .string(chatPath(agent.id, client)),
                "content": .string(JSON.array(rows).serialize()),
            ]))
    }

    // MARK: - cancellation (epoch-bump) + in-flight

    /// Snapshot the current epoch — call at the top of a stream so the
    /// stream's birth epoch is fixed before the first cancel poll.
    public func currentEpoch() -> UInt64 {
        cancelLock.lock()
        defer { cancelLock.unlock() }
        return interruptEpoch
    }

    /// True iff the stream should bail: its id was explicitly cancelled,
    /// or an interrupt fired after it started (epoch advanced).
    public func isStreamCancelled(streamId: String, startedAt: UInt64) -> Bool {
        cancelLock.lock()
        defer { cancelLock.unlock() }
        return cancelledStreams.contains(streamId) || startedAt < interruptEpoch
    }

    private func clearStreamCancel(_ id: String) {
        cancelLock.lock()
        defer { cancelLock.unlock() }
        cancelledStreams.remove(id)
    }

    private func bumpInFlight(_ delta: Int) {
        stateLock.lock()
        defer { stateLock.unlock() }
        inFlight = max(0, inFlight + delta)
    }

    /// Current in-flight stream count (for `backend_state` reporting).
    public func readInFlight() -> Int {
        stateLock.lock()
        defer { stateLock.unlock() }
        return inFlight
    }
}
