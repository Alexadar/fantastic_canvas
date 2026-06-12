// The one inbound choke point + the file_bridge-style verb gate.
//
// Swift mirror of py/rust `gate_inbound`: every io derivation (ws_bridge /
// cloud_bridge / web_ws / web_rest / file_bridge) calls THIS at one place to
// authorize an inbound action. Sealed-by-default lives in
// `IngressRules.resolve` (absent ⇒ DenyInbound), so a leg with no rule denies.

import FantasticJSON
import Foundation

/// Authorize an inbound `AuthAction` against a resolved ingress rule.
public func gateInbound(rule: IngressRule, action: AuthAction) -> AuthDecision {
    rule.authorize(action)
}

/// The fs-edge GATE — gate a verb on a leg given its rule meta (`ingress_rule` /
/// the legacy `auth` shorthand + the envelope `auth_token`). Lifecycle/discovery
/// verbs (`reflect`/`boot`/`shutdown`) bypass the gate so a SEALED bridge is
/// still discoverable. Returns `nil` to ADMIT, or a deny JSON
/// `{error, reason:"unauthorized", hint}`. Used by `file_bridge` (and the web
/// legs) — the same sealed-by-default choke point as the cross-kernel bridges.
public func gateVerb(
    ingressRule: JSON?,
    auth: JSON?,
    authToken: String?,
    agentId: String,
    verb: String
) -> JSON? {
    if verb == "reflect" || verb == "boot" || verb == "shutdown" { return nil }
    let rule: IngressRule
    do {
        rule = try resolveIngress(ingressRule: ingressRule, auth: auth)
    } catch {
        return .object(["error": .string("\(error)")])
    }
    let action = AuthAction(kind: "call", target: agentId, verb: verb, token: authToken)
    if case .deny(let reason) = gateInbound(rule: rule, action: action) {
        return .object([
            "error": .string(reason),
            "reason": .string("unauthorized"),
            "hint": .string(
                "the fs edge is sealed; open it: update_agent <id> ingress_rule=allow_all"),
        ])
    }
    return nil
}
