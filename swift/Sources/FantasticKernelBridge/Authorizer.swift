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
import Foundation

/// One inbound request the peer is asking this leg to perform locally.
public struct AuthAction: Sendable {
    /// `"call"` (gated) | `"watch"` | `"unwatch"`.
    public let kind: String
    /// The local agent id the peer addressed.
    public let target: String
    /// `payload["type"]` — the verb requested (e.g. `"reflect"`).
    public let verb: String
    /// The `auth_token` the peer attached to this call on the frame ENVELOPE, if any
    /// (read by the `password` policy; the dispatched payload never carries it).
    public let token: String?

    public init(kind: String, target: String, verb: String, token: String? = nil) {
        self.kind = kind
        self.target = target
        self.verb = verb
        self.token = token
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
    /// The token this leg PRESENTS on its own outbound `call`s (attached to the
    /// frame envelope by `forward`). Default `nil` — only credential-bearing
    /// policies (`password`) return one, so non-`password` legs keep today's exact
    /// wire shape (no `auth_token` field).
    func credential() -> String?
}

extension Authorizer {
    public func credential() -> String? { nil }
}

/// Content-blind constant-time compare given equal length (the length is not
/// secret — same posture as Python's `hmac.compare_digest`). Avoids a timing oracle
/// on the group token.
func constantTimeEquals(_ a: String, _ b: String) -> Bool {
    let x = Array(a.utf8)
    let y = Array(b.utf8)
    if x.count != y.count { return false }
    var diff: UInt8 = 0
    for i in 0..<x.count { diff |= x[i] ^ y[i] }
    return diff == 0
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

/// Kernel-group membership by a shared secret read from an env var (default
/// `FANTASTIC_GROUP_TOKEN`). Authorize an inbound `call` only if its envelope
/// `auth_token` equals the group token; symmetric — `credential()` PRESENTS the
/// same token on outbound calls, so one config makes a leg a full group member.
/// Fail-closed: an unset/empty env var refuses every inbound `call`. In Swift this
/// is enforced on the cloud_bridge leg only (its sole inbound-call dispatcher).
public struct Password: Authorizer {
    public let tokenEnv: String
    public init(tokenEnv: String = "FANTASTIC_GROUP_TOKEN") { self.tokenEnv = tokenEnv }

    private func token() -> String? {
        let v = ProcessInfo.processInfo.environment[tokenEnv]
        return (v?.isEmpty == false) ? v : nil  // present-but-empty ⇒ unset
    }

    public func authorize(_ action: AuthAction) -> AuthDecision {
        guard action.kind == "call" else { return .allow }
        guard let expected = token() else {
            return .deny("group token unset (\(tokenEnv))")
        }
        if let presented = action.token, constantTimeEquals(presented, expected) {
            return .allow
        }
        return .deny("invalid or missing group token")
    }

    public func credential() -> String? { token() }
}

/// Thrown by `makeAuthorizer` when the `auth` field names an unknown policy or
/// is malformed — fails the boot loudly rather than silently mis-securing.
public struct AuthPolicyError: Error, CustomStringConvertible {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var description: String { message }
}

/// The active auth policy NAME for reflect — string form is the name itself, object
/// form is its `policy` key, absent ⇒ `allow_all`. Never surfaces the policy config.
public func authPolicyName(_ auth: JSON?) -> String {
    switch auth {
    case .some(.string(let s)) where !s.isEmpty: return s
    case .some(.object(let o)): return o["policy"]?.asString ?? "allow_all"
    default: return "allow_all"
    }
}

/// Resolve the leg's `auth` record field to an Authorizer. Absent/null/empty ⇒
/// `AllowAll` (back-compat). String now (`"deny_inbound"`); the object form
/// (`{"policy": "<name>", ...}`) is accepted for forward-compat. Unknown policy ⇒
/// throws `AuthPolicyError`.
public func makeAuthorizer(_ auth: JSON?) throws -> Authorizer {
    guard let auth else { return AllowAll() }
    let name: String
    var tokenEnv = "FANTASTIC_GROUP_TOKEN"
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
        if let te = o["token_env"]?.asString { tokenEnv = te }  // sibling config
    default:
        throw AuthPolicyError("unsupported auth value")
    }
    switch name {
    case "allow_all": return AllowAll()
    case "deny_inbound": return DenyInbound()
    case "password": return Password(tokenEnv: tokenEnv)
    default: throw AuthPolicyError("unknown policy \"\(name)\"")
    }
}
