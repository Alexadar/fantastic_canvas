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
    /// The `auth_token` the peer attached to this call, if any (read by the
    /// `password` policy; `None` for an unauthenticated frame).
    pub token: Option<&'a str>,
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

    /// The token this leg PRESENTS on its own outbound `call`s (attached to the
    /// frame by `forward`). Default `None` — only credential-bearing policies
    /// (`password`) return one, so non-`password` legs keep today's exact wire
    /// shape (no `auth_token` field).
    fn credential(&self) -> Option<String> {
        None
    }
}

/// Constant-time byte compare (content-blind given equal length; the length is
/// not secret — same posture as Python's `hmac.compare_digest`). Avoids a timing
/// oracle on the group token without pulling a crypto dependency.
fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
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

/// Kernel-group membership by a shared secret. Authorize an inbound `call` only if
/// it carries an `auth_token` equal to this leg's group token, read from an env var
/// (default `FANTASTIC_GROUP_TOKEN`) so the secret never touches the portable
/// `.fantastic` workdir. Symmetric: `credential()` PRESENTS the same token on
/// outbound calls, so one config makes a leg a full group member (presents + checks).
/// Fail-closed: an unset/empty env var refuses every inbound `call`.
pub struct Password {
    token_env: String,
}

impl Password {
    /// Env var consulted when the record names none.
    pub const DEFAULT_ENV: &'static str = "FANTASTIC_GROUP_TOKEN";

    fn token(&self) -> Option<String> {
        std::env::var(&self.token_env)
            .ok()
            .filter(|s| !s.is_empty()) // present-but-empty ⇒ unset
    }
}

impl Authorizer for Password {
    fn authorize(&self, action: &Action) -> Decision {
        if action.kind != "call" {
            return Decision::Allow; // watch/unwatch already ignored by the read loop
        }
        let Some(expected) = self.token() else {
            return Decision::Deny(format!("group token unset ({})", self.token_env));
        };
        match action.token {
            Some(p) if constant_time_eq(p.as_bytes(), expected.as_bytes()) => Decision::Allow,
            _ => Decision::Deny("invalid or missing group token".to_string()),
        }
    }

    fn credential(&self) -> Option<String> {
        self.token()
    }
}

/// Resolve the leg's `auth` record field to an Authorizer. Absent/null ⇒
/// `AllowAll` (back-compat). String form (`"deny_inbound"`) or object form
/// (`{"policy": "<name>", ...sibling config}`) — the object's sibling keys feed the
/// policy (e.g. `{"policy":"password","token_env":"FOO"}`). Unknown policy ⇒ `Err`
/// (fails the boot loudly rather than silently mis-securing).
pub fn make_authorizer(auth: Option<&Value>) -> Result<Arc<dyn Authorizer>, String> {
    let Some(auth) = auth else {
        return Ok(Arc::new(AllowAll));
    };
    // Split into (policy name, optional object carrying sibling config).
    let (name, obj) = match auth {
        Value::Null => return Ok(Arc::new(AllowAll)),
        Value::String(s) if s.is_empty() => return Ok(Arc::new(AllowAll)),
        Value::String(s) => (s.as_str(), None),
        Value::Object(o) => {
            let name = o
                .get("policy")
                .and_then(Value::as_str)
                .ok_or_else(|| "auth object missing 'policy'".to_string())?;
            (name, Some(o))
        }
        other => return Err(format!("unsupported auth value {other:?}")),
    };
    match name {
        "allow_all" => Ok(Arc::new(AllowAll)),
        "deny_inbound" => Ok(Arc::new(DenyInbound)),
        "password" => {
            let token_env = obj
                .and_then(|o| o.get("token_env"))
                .and_then(Value::as_str)
                .unwrap_or(Password::DEFAULT_ENV)
                .to_string();
            Ok(Arc::new(Password { token_env }))
        }
        other => Err(format!("unknown policy {other:?}")),
    }
}
