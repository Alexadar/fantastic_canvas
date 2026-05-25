// Spatial UI host agent.
//
// Mirrors Rust's `fantastic-canvas-backend::CanvasBackendBundle`.
// Tracks "members" (the agents shown in the canvas) + their
// positions; canvas-webapp queries via `discover` + `get_webapp`.

import FantasticJSON
import FantasticKernel
import Foundation
import OrderedCollections

public let HANDLER_MODULE = "canvas_backend.tools"

public struct CanvasBackendBundle: AgentBundle {
    public let name = "canvas_backend"
    public init() {}

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
                "kind": .string("canvas_backend"),
                "sentence": .string("Spatial UI host — tracks members + positions."),
                "members": .integer(Int64(membersOf(agent: agent).count)),
                "verbs": [
                    "add_agent": "args: id, x?, y?, w?, h?.",
                    "remove_agent": "args: id.",
                    "discover": "args: x, y, w, h. Returns intersecting members.",
                ] as JSON,
            ] as JSON
        case "boot", "shutdown":
            return .object(["ok": .bool(true)])
        case "add_agent":
            return addAgentVerb(agent: agent, payload: payload, kernel: kernel)
        case "remove_agent":
            return removeAgentVerb(agent: agent, payload: payload, kernel: kernel)
        case "discover":
            return discoverVerb(agent: agent, payload: payload)
        case "list_members":
            return .object([
                "members": .array(membersOf(agent: agent).map { .object($0) })
            ])
        default:
            return .object(["error": .string("unknown verb \(verb)")])
        }
    }

    private func membersOf(agent: Agent) -> [OrderedDictionary<String, JSON>] {
        guard let arr = agent.metaValue(forKey: "members")?.asArray else { return [] }
        return arr.compactMap { v in
            if case let .object(m) = v { return m }
            return nil
        }
    }

    private func addAgentVerb(agent: Agent, payload: JSON, kernel: Kernel) -> JSON {
        guard let memberId = payload["id"].asString else {
            return .object(["error": .string("add_agent requires id")])
        }
        var member: OrderedDictionary<String, JSON> = [:]
        member["id"] = .string(memberId)
        member["x"] = payload["x"].isNull ? .integer(0) : payload["x"]
        member["y"] = payload["y"].isNull ? .integer(0) : payload["y"]
        member["w"] = payload["w"].isNull ? .integer(320) : payload["w"]
        member["h"] = payload["h"].isNull ? .integer(240) : payload["h"]

        var current = membersOf(agent: agent)
        current.removeAll { $0["id"]?.asString == memberId }
        current.append(member)
        agent.updateMeta([
            "members": .array(current.map { .object($0) })
        ])
        try? Persistence.persist(agent: agent, storage: kernel.storage)
        return .object([
            "ok": .bool(true),
            "id": .string(memberId),
        ])
    }

    private func removeAgentVerb(agent: Agent, payload: JSON, kernel: Kernel) -> JSON {
        guard let memberId = payload["id"].asString else {
            return .object(["error": .string("remove_agent requires id")])
        }
        var current = membersOf(agent: agent)
        let before = current.count
        current.removeAll { $0["id"]?.asString == memberId }
        if current.count < before {
            agent.updateMeta([
                "members": .array(current.map { .object($0) })
            ])
            try? Persistence.persist(agent: agent, storage: kernel.storage)
        }
        return .object([
            "ok": .bool(true),
            "removed": .bool(current.count < before),
        ])
    }

    private func discoverVerb(agent: Agent, payload: JSON) -> JSON {
        let x = payload["x"].asDouble ?? 0
        let y = payload["y"].asDouble ?? 0
        let w = payload["w"].asDouble ?? 0
        let h = payload["h"].asDouble ?? 0
        let members = membersOf(agent: agent).filter { member in
            let mx = member["x"]?.asDouble ?? 0
            let my = member["y"]?.asDouble ?? 0
            let mw = member["w"]?.asDouble ?? 0
            let mh = member["h"]?.asDouble ?? 0
            return mx < x + w && mx + mw > x && my < y + h && my + mh > y
        }
        return .object(["members": .array(members.map { .object($0) })])
    }
}
