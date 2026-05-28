// `fantastic chat` — interactive REPL probe.
//
// Mirrors python/kernel/_modes.py:_repl_loop verbatim:
//
//     fantastic> list                          # list all agents
//     fantastic> add <bundle> [k=v ...]        # create_agent + boot
//     fantastic> delete <id>                   # delete_agent
//     fantastic> @<id> <text>                  # send {type:send, text}
//     fantastic> @<id> <verb> [k=v ...]        # send {type:verb, k:v}
//     fantastic> exit / quit / Ctrl-D          # quit
//
// Bootstraps the Apple app's BrainKernelHost.boot() agent surface
// (header_ui / actions_ui / recents_ui / chat_ui / banner_ui / fm /
// tools) inside the workdir so the FM agent has the same kernel to
// reflect on as it would in the app. No WebSocket, no memory bundle,
// no session-router — just enough wiring to see what Apple FM does
// when handed the canvas surface.
//
// Usage:
//   fantastic chat [<workdir>]
//
// Workdir defaults to `./.fantastic-chat` in CWD. Created on first
// run; rehydrates on subsequent runs.

import FantasticJSON
import FantasticKernel
import FantasticKernelStartup
import Foundation
import OrderedCollections

enum ChatMode {

    static func run(workdir: String) async {
        let fm = FileManager.default
        let url = URL(fileURLWithPath: workdir, isDirectory: true)
        try? fm.createDirectory(at: url, withIntermediateDirectories: true)

        printLine("== fantastic chat ==")
        printLine("workdir: \(url.path)")

        let kernel: Kernel
        do {
            kernel = try await startKernel(workdir: url.path, portHint: 0)
        } catch {
            printLine("kernel boot failed: \(error)")
            return
        }

        await seedAgentSurface(kernel: kernel)
        await reportFmAvailability(kernel: kernel)

        // One process-wide watcher tied to the fm agent's inbox. The
        // REPL drains it whenever a chat `@<id> send` is in flight.
        // Non-chat verbs ignore it.
        let watcherId = AgentId("cli_repl_\(UUID().uuidString.prefix(8))")
        kernel.watch(src: AgentId("fm"), watcher: watcherId)

        printLine("")
        printLine("commands (Python parity):")
        printLine("  list                       all agents")
        printLine("  add <bundle> [k=v ...]     create + boot")
        printLine("  delete <id>                delete an agent")
        printLine("  @<id> <text>               chat — send {type:send, text}")
        printLine("  @<id> <verb> [k=v ...]     RPC — send {type:verb, k:v}")
        printLine("  exit / quit / Ctrl-D       quit")
        printLine("")

        while true {
            print("fantastic> ", terminator: "")
            guard let raw = readLine() else { break }  // Ctrl-D
            let line = raw.trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if line == "exit" || line == "quit" { break }

            if line == "list" {
                await handleList(kernel: kernel)
                continue
            }
            if line.hasPrefix("add ") {
                await handleAdd(args: String(line.dropFirst(4)), kernel: kernel)
                continue
            }
            if line.hasPrefix("delete ") {
                await handleDelete(
                    id: String(line.dropFirst(7).trimmingCharacters(in: .whitespaces)),
                    kernel: kernel)
                continue
            }
            if line.hasPrefix("@") {
                await handleAt(line: line, kernel: kernel, watcherId: watcherId)
                continue
            }
            printLine(
                "  unknown command: \(line.debugDescription)  "
                    + "(try: list, add <bundle>, delete <id>, @<id> ...)")
        }

        printLine("\ngoodbye.")
    }

    // MARK: - Commands

    private static func handleList(kernel: Kernel) async {
        let reply = await kernel.send(
            AgentId("core"), .object(["type": .string("list_agents")]))
        for agent in reply["agents"].asArray ?? [] {
            let id = agent["id"].asString ?? "?"
            let hm = agent["handler_module"].asString ?? "<root>"
            printLine("  \(id)  →  \(hm)")
        }
    }

    private static func handleAdd(args raw: String, kernel: Kernel) async {
        let parts = splitArgs(raw)
        guard let bundle = parts.first else {
            printLine("  usage: add <bundle> [k=v ...]")
            return
        }
        // Convention: `<bundle>` → `<bundle>.tools` if no dot present.
        let handlerModule = bundle.contains(".") ? bundle : "\(bundle).tools"

        var payload: OrderedDictionary<String, JSON> = [
            "type": .string("create_agent"),
            "handler_module": .string(handlerModule),
        ]
        for p in parts.dropFirst() {
            guard let eq = p.firstIndex(of: "=") else { continue }
            let k = String(p[..<eq])
            let v = String(p[p.index(after: eq)...])
            payload[k] = coerce(v)
        }
        let reply = await kernel.send(AgentId("core"), .object(payload))
        if let id = reply["id"].asString {
            // Then boot.
            _ = await kernel.send(AgentId(id), .object(["type": .string("boot")]))
            printLine("  added \(id) (\(handlerModule))")
        } else if let err = reply["error"].asString {
            printLine("  add failed: \(err)")
        } else {
            printLine(reply.serialize())
        }
    }

    private static func handleDelete(id: String, kernel: Kernel) async {
        if id.isEmpty {
            printLine("  usage: delete <id>")
            return
        }
        let reply = await kernel.send(
            AgentId("core"),
            .object([
                "type": .string("delete_agent"),
                "id": .string(id),
            ]))
        if let err = reply["error"].asString {
            printLine("  delete failed: \(err)")
        } else {
            printLine("  deleted \(id)")
        }
    }

    /// Universal verb names that should be interpreted as RPC
    /// rather than chat text. Everything else falls through to
    /// chat (more useful default for a chat-style REPL).
    private static let knownRPCVerbs: Set<String> = [
        // Substrate verbs every agent answers
        "reflect", "boot", "shutdown", "get",
        // System verbs on core
        "list_agents", "create_agent", "delete_agent", "update_agent",
        // LLM-backend verbs
        "history", "interrupt", "backend_state",
    ]

    /// Handle the `@<id> ...` family — CHAT-FIRST:
    ///   @<id>                    → chat with empty text
    ///   @<id> <known-rpc-verb>   → RPC: {type:verb}
    ///   @<id> <verb> k=v ...     → RPC: {type:verb, k:v, ...}
    ///   @<id> anything else      → chat: {type:send, text:"anything else"}
    ///
    /// Departs from strict Python parity (Python treats `@fm hi` as
    /// RPC verb "hi" → unknown-verb error). Chat-first is friendlier
    /// for the FM agent's common-case usage.
    private static func handleAt(
        line: String, kernel: Kernel, watcherId: AgentId
    ) async {
        let rest = String(line.dropFirst()).trimmingCharacters(in: .whitespaces)
        if rest.isEmpty {
            printLine("  usage: @<id> <text> | @<id> <verb> k=v ...")
            return
        }
        let parts = splitArgs(rest)
        let target = parts[0]
        let argTokens = Array(parts.dropFirst())

        // Empty args → send empty chat.
        if argTokens.isEmpty {
            await chat(text: "", target: target, kernel: kernel, watcherId: watcherId)
            return
        }

        // Single non-kv token → KNOWN verb → RPC. Otherwise chat text.
        if argTokens.count == 1 && !argTokens[0].contains("=") {
            if knownRPCVerbs.contains(argTokens[0]) {
                let reply = await kernel.send(
                    AgentId(target),
                    .object(["type": .string(argTokens[0])])
                )
                printLine(reply.serializePretty(indent: 2))
            } else {
                // Treat the single word as chat text.
                await chat(
                    text: argTokens[0], target: target,
                    kernel: kernel, watcherId: watcherId
                )
            }
            return
        }

        // Any kv tokens → verb + kv args (RPC). If first token has no `=`,
        // it's the verb; otherwise verb defaults to "send".
        if argTokens.contains(where: { $0.contains("=") }) {
            let verb: String
            let kvTokens: [String]
            if argTokens[0].contains("=") {
                verb = "send"
                kvTokens = argTokens
            } else {
                verb = argTokens[0]
                kvTokens = Array(argTokens.dropFirst())
            }
            var payload: OrderedDictionary<String, JSON> = ["type": .string(verb)]
            for t in kvTokens {
                guard let eq = t.firstIndex(of: "=") else { continue }
                let k = String(t[..<eq])
                let v = String(t[t.index(after: eq)...])
                payload[k] = coerce(v)
            }
            // Verb is "send" → chat-stream. Anything else → one-shot RPC.
            if verb == "send" {
                let text = payload["text"]?.asString ?? ""
                await chat(
                    text: text, target: target, kernel: kernel, watcherId: watcherId)
            } else {
                let reply = await kernel.send(AgentId(target), .object(payload))
                printLine(reply.serializePretty(indent: 2))
            }
            return
        }

        // Plain prose after target → chat send.
        // Recover the literal text from `line` (skip "@", target,
        // and any whitespace after it) so we don't lose internal
        // whitespace from shell-style splitting.
        let dropped = line.dropFirst()  // skip @
        guard let rangeOfTarget = dropped.range(of: target) else {
            await chat(text: "", target: target, kernel: kernel, watcherId: watcherId)
            return
        }
        let textPart = dropped[rangeOfTarget.upperBound...].trimmingCharacters(
            in: .whitespaces)
        await chat(
            text: textPart, target: target, kernel: kernel, watcherId: watcherId)
    }

    /// Send `{type:"send", text}` to the target agent, then drain the
    /// watcher inbox printing token deltas until the matching stream's
    /// `done` event arrives.
    ///
    /// The watcher is `kernel.watch(src: fm, ...)` — so this only
    /// streams replies when target == "fm". Targets that don't emit
    /// on the fm inbox just print the immediate reply.
    private static func chat(
        text: String, target: String, kernel: Kernel, watcherId: AgentId
    ) async {
        let sendReply = await kernel.send(
            AgentId(target),
            .object([
                "type": .string("send"),
                "text": .string(text),
                "client_id": .string("cli"),
            ]))
        guard let streamId = sendReply["stream_id"].asString else {
            if let err = sendReply["error"].asString {
                printLine("  [send error] \(err)")
            } else {
                printLine(sendReply.serializePretty(indent: 2))
            }
            return
        }
        guard target == "fm" else {
            // Non-fm targets — we don't have a watcher for them.
            printLine(sendReply.serializePretty(indent: 2))
            return
        }
        let inbox = kernel.ensureInbox(watcherId)
        print("  ", terminator: "")  // assistant bubble indent
        fflush(stdout)
        for await event in inbox {
            if let sid = event["stream_id"].asString, sid != streamId { continue }
            switch event["type"].asString {
            case "token":
                if let delta = event["delta"].asString, !delta.isEmpty {
                    print(delta, terminator: "")
                    fflush(stdout)
                }
            case "reset":
                print("\r\u{001B}[2K  ", terminator: "")  // wipe + re-indent
                fflush(stdout)
            case "done":
                if let err = event["error"].asString {
                    printLine("\n  [fm error] \(err)")
                } else {
                    printLine("")
                }
                return
            default:
                break
            }
        }
    }

    // MARK: - Agent surface seeding (Apple app parity)

    /// Same agent set BrainKernelHost.boot() creates in the Apple app.
    /// Idempotent — only creates agents that don't already exist.
    private static func seedAgentSurface(kernel: Kernel) async {
        let surface: [(id: String, handler: String, meta: OrderedDictionary<String, JSON>)] = [
            ("header_ui", "proxy_agent.tools", [:]),
            ("actions_ui", "proxy_agent.tools", [:]),
            ("recents_ui", "proxy_agent.tools", [:]),
            ("chat_ui", "proxy_agent.tools", [:]),
            ("banner_ui", "proxy_agent.tools", [:]),
            ("tools", "tools.tools", [:]),
            (
                "fm", "foundation_models_backend.tools",
                [
                    "instructions": .string(canvasSystemPrompt),
                    // 0.2 (was 0.4) — tighter sampling reduces the
                    // "fill in plausible-sounding description from
                    // training prior" failure mode we saw on probe 2.
                    "temperature": .double(0.2),
                ]
            ),
        ]

        for entry in surface {
            if kernel.agent(AgentId(entry.id)) != nil {
                printLine("  agent \(entry.id): already present")
                continue
            }
            var payload: OrderedDictionary<String, JSON> = [
                "type": .string("create_agent"),
                "handler_module": .string(entry.handler),
                "id": .string(entry.id),
            ]
            for (k, v) in entry.meta { payload[k] = v }
            let reply = await kernel.send(AgentId("core"), .object(payload))
            if let err = reply["error"].asString {
                printLine("  agent \(entry.id): FAILED — \(err)")
            } else {
                printLine("  agent \(entry.id): created (\(entry.handler))")
            }
        }
    }

    private static func reportFmAvailability(kernel: Kernel) async {
        let r = await kernel.send(
            AgentId("fm"), .object(["type": .string("backend_state")]))
        let available = r["apple_intelligence_available"].asBool ?? false
        let reason = r["reason"].asString ?? "unknown"
        if available {
            printLine("fm: ready (\(reason))")
        } else {
            printLine("fm: UNAVAILABLE (\(reason))")
            printLine(
                "    chat will return stub replies until macOS 26 +"
                    + " Apple Intelligence is enabled on this host.")
        }
    }

    private static let canvasSystemPrompt = """
        You are a Fantastic canvas assistant attached to a local kernel.

        Rules:
          1. ALWAYS use a tool before claiming any fact about kernel \
             state. Prefer aggregators (list_agents, list_proxy_hosts) \
             over chained reflect calls.
          2. Quote facts ONLY from tool replies. Never invent.
          3. When listing agents, include EVERY entry from the tool \
             result. If an entry's `sentence` is null, use its \
             `kind` field as the description (e.g., "proxy_agent"). \
             Never drop entries. Never guess from agent names.
          4. Answer concisely. Lists are fine for enumerations. \
             No emojis.
          5. Never invent agent IDs.
        """

    // MARK: - Parsing helpers (match Python's shlex.split semantics
    // for common cases without bringing in a full shell parser)

    /// Split a line on whitespace, honoring double-quoted segments.
    /// Matches Python `shlex.split` for the cases the REPL exercises.
    private static func splitArgs(_ s: String) -> [String] {
        var out: [String] = []
        var cur = ""
        var inQuotes = false
        for ch in s {
            if ch == "\"" {
                inQuotes.toggle()
                continue
            }
            if ch.isWhitespace && !inQuotes {
                if !cur.isEmpty {
                    out.append(cur)
                    cur = ""
                }
                continue
            }
            cur.append(ch)
        }
        if !cur.isEmpty { out.append(cur) }
        return out
    }

    /// Coerce a string value into JSON. Mirrors Python's `_coerce`:
    ///   true/false → bool
    ///   integer    → integer
    ///   double     → double
    ///   else       → string
    private static func coerce(_ v: String) -> JSON {
        switch v.lowercased() {
        case "true": return .bool(true)
        case "false": return .bool(false)
        default: break
        }
        if let i = Int64(v) { return .integer(i) }
        if let d = Double(v) { return .double(d) }
        return .string(v)
    }

    private static func printLine(_ s: String) {
        print(s)
        fflush(stdout)
    }
}
