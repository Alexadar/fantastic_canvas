// Spatial UI front-end (canvas).
//
// Mirrors Rust's `fantastic-canvas-webapp::CanvasWebappBundle`.
// Serves the canvas.html (loaded as a SwiftPM Resource) at `/<id>/`
// via the web bundle's `render_html` route.

import FantasticJSON
import FantasticKernel
import Foundation

public let HANDLER_MODULE = "canvas_webapp.tools"

public struct CanvasWebappBundle: AgentBundle {
    public let name = "canvas_webapp"
    public init() {}

    /// Bundled canvas.html resource, loaded once at first access.
    private static let html: String = {
        if let url = Bundle.module.url(
            forResource: "canvas", withExtension: "html"),
            let data = try? Data(contentsOf: url),
            let s = String(data: data, encoding: .utf8)
        {
            return s
        }
        return "<!doctype html><html><body>canvas.html unavailable</body></html>"
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
                "kind": .string("canvas_webapp"),
                "sentence": .string(
                    "Canvas webapp — serves canvas.html and pairs with a canvas_backend via upstream_id."),
                "upstream_id": kernel.agent(agentId)?.metaValue(forKey: "upstream_id")
                    ?? .null,
                "verbs": [
                    "render_html": "Returns the canvas surface HTML.",
                    "get_webapp": "Returns iframe descriptor + URL.",
                ] as JSON,
            ] as JSON
        case "boot", "shutdown":
            return .object(["ok": .bool(true)])
        case "render_html":
            return .object(["html": .string(Self.html)])
        case "get_webapp":
            return [
                "kind": .string("canvas_webapp"),
                "url": .string("/\(agentId.value)/"),
            ] as JSON
        default:
            return .object(["error": .string("unknown verb \(verb)")])
        }
    }
}
