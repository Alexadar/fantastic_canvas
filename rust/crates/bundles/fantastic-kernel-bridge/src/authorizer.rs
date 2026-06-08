//! Bridge authorization — the per-leg, declarative auth seam.
//!
//! A bridge leg is symmetric by default: once connected, either side can `call`
//! any agent/verb on the other. An `auth` field on the agent record selects a
//! POLICY the read loop consults before dispatching an inbound `call` — like an
//! nginx allow/deny rule, evaluated at ONE choke point. Enforced on the RECEIVER
//! (the leg refuses the peer's frame on arrival), so a compromised peer can't
//! bypass it.
//!
//! v1 ships two policies:
//!   - `allow_all`   (default — absent `auth` ⇒ this) — today's full symmetric duplex.
//!   - `deny_inbound` — refuse every inbound `call` (the one-way / hub→spoke push).
//!     Inbound `watch`/`unwatch` are already ignored by the read loop, so they're
//!     denied-by-omission.
//!
//! The abstraction is extensible (future: per-peer allowlist by the pinned
//! Ed25519 pubkey, target/verb scoping) WITHOUT touching the engine — a new
//! policy, not a new gate. [`Action`] is the extension point (a `peer_pubkey`
//! field lands when per-peer rules ship; rust must surface
//! `CloudTransport::peer_pubkey` through the `BridgeTransport` trait first).

use serde_json::Value;
use std::sync::Arc;

/// One inbound request the peer is asking this leg to perform locally.
pub struct Action<'a> {
    /// `"call"` (gated) | `"watch"` | `"unwatch"`.
    pub kind: &'a str,
    /// The local agent id the peer addressed.
    pub target: &'a str,
    /// `payload["type"]` — the verb requested (e.g. `"reflect"`).
    pub verb: &'a str,
}

/// The authorizer's verdict on an [`Action`].
pub enum Decision {
    /// Permit the inbound action — dispatch `kernel.send`.
    Allow,
    /// Refuse it; the read loop replies `{error, reason:"unauthorized"}`.
    Deny(String),
}

/// Decides whether the peer may perform an inbound `action` on this leg.
/// Object-safe so the gate stays policy-agnostic (`Arc<dyn Authorizer>`).
pub trait Authorizer: Send + Sync {
    /// Authorize one inbound action.
    fn authorize(&self, action: &Action) -> Decision;
}

/// Full symmetric duplex — the default; a true no-op.
pub struct AllowAll;

impl Authorizer for AllowAll {
    fn authorize(&self, _action: &Action) -> Decision {
        Decision::Allow
    }
}

/// One-way push: refuse every inbound `call` (peer can't call/reflect us).
pub struct DenyInbound;

impl Authorizer for DenyInbound {
    fn authorize(&self, action: &Action) -> Decision {
        if action.kind == "call" {
            Decision::Deny("inbound calls denied by policy".to_string())
        } else {
            Decision::Allow // watch/unwatch already ignored by the read loop
        }
    }
}

/// Resolve the leg's `auth` record field to an Authorizer. Absent/null ⇒
/// `AllowAll` (back-compat). String now (`"deny_inbound"`); the object form
/// (`{"policy": "<name>", ...}`) is accepted for forward-compat. Unknown policy ⇒
/// `Err` (fails the boot loudly rather than silently mis-securing).
pub fn make_authorizer(auth: Option<&Value>) -> Result<Arc<dyn Authorizer>, String> {
    let Some(auth) = auth else {
        return Ok(Arc::new(AllowAll));
    };
    let name = match auth {
        Value::Null => return Ok(Arc::new(AllowAll)),
        Value::String(s) if s.is_empty() => return Ok(Arc::new(AllowAll)),
        Value::String(s) => s.as_str(),
        Value::Object(o) => o
            .get("policy")
            .and_then(Value::as_str)
            .ok_or_else(|| "auth object missing 'policy'".to_string())?,
        other => return Err(format!("unsupported auth value {other:?}")),
    };
    match name {
        "allow_all" => Ok(Arc::new(AllowAll)),
        "deny_inbound" => Ok(Arc::new(DenyInbound)),
        other => Err(format!("unknown policy {other:?}")),
    }
}
