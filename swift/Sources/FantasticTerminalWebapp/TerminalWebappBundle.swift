// Terminal UI front-end (xterm).
//
// Mirrors Rust's `fantastic-terminal-webapp::TerminalWebappBundle`.
// Serves terminal index.html at `/<id>/`.

import FantasticJSON
import FantasticKernel
import Foundation

public let HANDLER_MODULE = "terminal_webapp.tools"

public struct TerminalWebappBundle: AgentBundle {
    public let name = "terminal_webapp"
    public init() {}

    private static let html: String = {
        if let url = Bundle.module.url(forResource: "index", withExtension: "html"),
            let data = try? Data(contentsOf: url),
            let s = String(data: data, encoding: .utf8)
        {
            return s
        }
        return "<!doctype html><html><body>terminal index.html unavailable</body></html>"
    }()

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
                "kind": .string("terminal_webapp"),
                "upstream_id": kernel.agent(agentId)?.metaValue(forKey: "upstream_id") ?? .null,
                "verbs": [
                    "render_html": "Returns the terminal xterm surface.",
                    "get_webapp": "Returns iframe descriptor + URL.",
                ] as JSON,
            ] as JSON
        case "boot", "shutdown":
            return .object(["ok": .bool(true)])
        case "render_html":
            return .object(["html": .string(Self.html)])
        case "get_webapp":
            return [
                "kind": .string("terminal_webapp"),
                "url": .string("/\(agentId.value)/"),
            ] as JSON
        default:
            return .object(["error": .string("unknown verb \(verb)")])
        }
    }
}
