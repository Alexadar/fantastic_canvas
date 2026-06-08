// Bridge authorization — the per-leg, declarative auth seam.
//
// Swift mirror of the canonical Python `bridge_core._authorizer` (and the Rust
// `authorizer`). A bridge leg is symmetric by default: once connected, either
// side can `call` any agent/verb on the other. An `auth` field on the agent
// record selects a POLICY consulted before dispatching an inbound `call` — like
// an nginx allow/deny rule, evaluated at ONE choke point. Enforced on the
// RECEIVER (the leg refuses the peer's frame on arrival), so a compromised peer
// can't bypass it.
//
// v1 ships two policies:
//   - `allow_all`   (default — absent `auth` ⇒ this) — today's full symmetric duplex.
//   - `deny_inbound` — refuse every inbound `call` (the one-way / hub→spoke push).
//     Inbound `watch`/`unwatch` are already ignored, so they're denied-by-omission.
//
// SWIFT SPECIFIC: there is no shared read loop. In-memory `forward` is a direct
// kernel call (no inbound-`call` frame) and `ws` is an asymmetric client — the
// ONLY inbound `call` dispatcher is `CloudBridgeTransport.dispatch`. So
// `deny_inbound` is cloud-only in Swift, correct-by-construction (the relay e2e
// matrix covers Swift's real inbound path). The abstraction is extensible
// (future: per-peer allowlist by the pinned Ed25519 pubkey) WITHOUT touching the
// transport — a new policy, not a new gate; `AuthAction` is the extension point.

import FantasticJSON

/// One inbound request the peer is asking this leg to perform locally.
public struct AuthAction: Sendable {
    /// `"call"` (gated) | `"watch"` | `"unwatch"`.
    public let kind: String
    /// The local agent id the peer addressed.
    public let target: String
    /// `payload["type"]` — the verb requested (e.g. `"reflect"`).
    public let verb: String

    public init(kind: String, target: String, verb: String) {
        self.kind = kind
        self.target = target
        self.verb = verb
    }
}

/// The authorizer's verdict on an `AuthAction`.
public enum AuthDecision: Sendable {
    /// Permit the inbound action — dispatch `kernel.send`.
    case allow
    /// Refuse it; the dispatcher replies `{error, reason:"unauthorized"}`.
    case deny(String)
}

/// Decides whether the peer may perform an inbound `action` on this leg.
public protocol Authorizer: Sendable {
    func authorize(_ action: AuthAction) -> AuthDecision
}

/// Full symmetric duplex — the default; a true no-op.
public struct AllowAll: Authorizer {
    public init() {}
    public func authorize(_ action: AuthAction) -> AuthDecision { .allow }
}

/// One-way push: refuse every inbound `call` (peer can't call/reflect us).
public struct DenyInbound: Authorizer {
    public init() {}
    public func authorize(_ action: AuthAction) -> AuthDecision {
        action.kind == "call"
            ? .deny("inbound calls denied by policy")
            : .allow  // watch/unwatch already ignored by the dispatcher
    }
}

/// Thrown by `makeAuthorizer` when the `auth` field names an unknown policy or
/// is malformed — fails the boot loudly rather than silently mis-securing.
public struct AuthPolicyError: Error, CustomStringConvertible {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var description: String { message }
}

/// Resolve the leg's `auth` record field to an Authorizer. Absent/null/empty ⇒
/// `AllowAll` (back-compat). String now (`"deny_inbound"`); the object form
/// (`{"policy": "<name>", ...}`) is accepted for forward-compat. Unknown policy ⇒
/// throws `AuthPolicyError`.
public func makeAuthorizer(_ auth: JSON?) throws -> Authorizer {
    guard let auth else { return AllowAll() }
    let name: String
    switch auth {
    case .null:
        return AllowAll()
    case .string(let s):
        if s.isEmpty { return AllowAll() }
        name = s
    case .object(let o):
        guard let p = o["policy"]?.asString else {
            throw AuthPolicyError("auth object missing 'policy'")
        }
        name = p
    default:
        throw AuthPolicyError("unsupported auth value")
    }
    switch name {
    case "allow_all": return AllowAll()
    case "deny_inbound": return DenyInbound()
    default: throw AuthPolicyError("unknown policy \"\(name)\"")
    }
}
