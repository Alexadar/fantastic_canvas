"""bridge_core authorization — the per-leg, declarative auth seam.

A bridge leg is symmetric by default: once connected, either side can `call` any
agent/verb on the other. An `auth` field on the agent record selects a POLICY the
read loop consults before dispatching an inbound `call` — like an nginx allow/deny
rule, evaluated at ONE choke point. Enforced on the RECEIVER (the leg drops the
peer's frame on arrival), so a compromised peer can't bypass it.

v1 ships three policies:
  - `allow_all`   (default — absent `auth` ⇒ this) — today's full symmetric duplex.
  - `deny_inbound` — refuse every inbound `call` (the one-way / hub→spoke push: the
    master ignores the spoke's calls/`reflect`). Inbound `watch`/`unwatch` are
    already ignored by the read loop, so they're denied-by-omission.
  - `password` — kernel-GROUP membership by a shared secret: authorize an inbound
    `call` only if it carries an `auth_token` matching this leg's group token (read
    from an env var, default `FANTASTIC_GROUP_TOKEN`). The credential-bearing first
    concrete policy — the bridge-authz analog of the relay's `password` provider
    (abstract auth, password impl). Symmetric for a group: the same policy both
    PRESENTS the token on outbound calls (`credential()`) and CHECKS it on inbound.

The credential a leg presents on its own outbound calls is `Authorizer.credential()`
(default `None` — only `password` returns one), so the engine's `forward` stays
policy-agnostic: it attaches whatever the authorizer hands it, nothing more.

The abstraction is extensible (future: per-peer allowlist by the pinned Ed25519
pubkey, target/verb scoping) WITHOUT touching the engine — a new policy, not a new
gate. `Action` is the extension point: it already carries the full `payload` (so the
`password` check is new-class-only), and a `peer_pubkey` field lands when per-peer
rules ship (the verified key is already on `st.extra["verified_partner"]`).
"""

from __future__ import annotations

import hmac
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields, is_dataclass


@dataclass(frozen=True)
class Action:
    """One inbound request the peer is asking this leg to perform locally."""

    kind: str  # "call" (gated) | "watch" | "unwatch"
    target: str  # the local agent id the peer addressed
    verb: str  # payload["type"] — the verb requested (e.g. "reflect")
    payload: dict  # the inbound payload (dispatched verbatim — NO auth token in it)
    token: str | None = (
        None  # the frame-envelope `auth_token`, if the peer attached one
    )


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


ALLOW = Decision(True)


class Authorizer(ABC):
    """Decides whether the peer may perform an inbound `action` on this leg."""

    @abstractmethod
    def authorize(self, action: Action) -> Decision: ...

    def credential(self) -> str | None:
        """The token this leg PRESENTS on its own outbound `call`s (attached to the
        frame by the engine's `forward`). Default `None` — only credential-bearing
        policies (`password`) return one, so non-`password` legs keep today's exact
        wire shape (no `auth_token` field)."""
        return None


class AllowAll(Authorizer):
    """Full symmetric duplex — the default; a true no-op."""

    def authorize(self, action: Action) -> Decision:
        return ALLOW


class DenyInbound(Authorizer):
    """One-way push: refuse every inbound `call` (peer can't call/reflect us)."""

    def authorize(self, action: Action) -> Decision:
        if action.kind == "call":
            return Decision(False, "inbound calls denied by policy")
        return ALLOW  # watch/unwatch already ignored by the read loop


@dataclass(frozen=True)
class Password(Authorizer):
    """Kernel-group membership by a shared secret. Authorize an inbound `call` only
    if it carries an `auth_token` equal to this leg's group token, read from an env
    var (default `FANTASTIC_GROUP_TOKEN`) so the secret never touches the portable
    `.fantastic` workdir. Symmetric: `credential()` PRESENTS the same token on
    outbound calls, so one config makes a leg a full group member (presents + checks).

    Fail-closed: if the env var is unset/empty the leg refuses every inbound `call`
    (a misconfigured group token must not silently allow). Constant-time compare.
    """

    token_env: str = "FANTASTIC_GROUP_TOKEN"

    def _token(self) -> str | None:
        tok = os.environ.get(self.token_env)
        return tok or None  # treat present-but-empty as unset

    def authorize(self, action: Action) -> Decision:
        if action.kind != "call":
            return ALLOW  # watch/unwatch already ignored by the read loop
        expected = self._token()
        if expected is None:
            return Decision(False, f"group token unset ({self.token_env})")
        presented = (
            action.token
        )  # the frame-envelope token (NOT the dispatched payload)
        if isinstance(presented, str) and hmac.compare_digest(presented, expected):
            return ALLOW
        return Decision(False, "invalid or missing group token")

    def credential(self) -> str | None:
        return self._token()


_POLICIES = {"allow_all": AllowAll, "deny_inbound": DenyInbound, "password": Password}


def make_authorizer(record: dict) -> Authorizer:
    """Resolve the leg's `auth` record field to an Authorizer. Absent ⇒ AllowAll
    (back-compat). String form (`"deny_inbound"`) or object form
    (`{"policy": "<name>", ...sibling config}`) — the object's sibling keys are
    threaded into the policy constructor (e.g. `{"policy":"password",
    "token_env":"FOO"}` ⇒ `Password(token_env="FOO")`), tolerantly filtered to the
    policy's own fields so an extra key can't crash the boot. Unknown policy ⇒
    ValueError (fails the boot loudly rather than silently mis-securing)."""
    auth = record.get("auth")
    if not auth:
        return AllowAll()
    if isinstance(auth, str):
        name, cfg = auth, {}
    else:
        name = auth.get("policy")
        cfg = {k: v for k, v in auth.items() if k != "policy"}
    cls = _POLICIES.get(name)
    if cls is None:
        raise ValueError(f"unknown policy {name!r}")
    if is_dataclass(cls):  # thread object-form config into the policy's fields
        allowed = {f.name for f in fields(cls)}
        cfg = {k: v for k, v in cfg.items() if k in allowed}
    else:
        cfg = {}  # AllowAll / DenyInbound take no config
    return cls(**cfg)
