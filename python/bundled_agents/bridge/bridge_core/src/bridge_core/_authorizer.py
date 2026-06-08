"""bridge_core authorization — the per-leg, declarative auth seam.

A bridge leg is symmetric by default: once connected, either side can `call` any
agent/verb on the other. An `auth` field on the agent record selects a POLICY the
read loop consults before dispatching an inbound `call` — like an nginx allow/deny
rule, evaluated at ONE choke point. Enforced on the RECEIVER (the leg drops the
peer's frame on arrival), so a compromised peer can't bypass it.

v1 ships two policies:
  - `allow_all`   (default — absent `auth` ⇒ this) — today's full symmetric duplex.
  - `deny_inbound` — refuse every inbound `call` (the one-way / hub→spoke push: the
    master ignores the spoke's calls/`reflect`). Inbound `watch`/`unwatch` are
    already ignored by the read loop, so they're denied-by-omission.

The abstraction is extensible (future: per-peer allowlist by the pinned Ed25519
pubkey, target/verb scoping) WITHOUT touching the engine — a new policy, not a new
gate. `Action` is the extension point (a `peer_pubkey` field lands when per-peer
rules ship; the verified key is already on `st.extra["verified_partner"]`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """One inbound request the peer is asking this leg to perform locally."""

    kind: str  # "call" (gated) | "watch" | "unwatch"
    target: str  # the local agent id the peer addressed
    verb: str  # payload["type"] — the verb requested (e.g. "reflect")
    payload: dict  # the full inbound payload


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


ALLOW = Decision(True)


class Authorizer(ABC):
    """Decides whether the peer may perform an inbound `action` on this leg."""

    @abstractmethod
    def authorize(self, action: Action) -> Decision: ...


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


_POLICIES = {"allow_all": AllowAll, "deny_inbound": DenyInbound}


def make_authorizer(record: dict) -> Authorizer:
    """Resolve the leg's `auth` record field to an Authorizer. Absent ⇒ AllowAll
    (back-compat). String now (`"deny_inbound"`); the object form
    (`{"policy": "<name>", ...}`) is accepted for forward-compat. Unknown policy ⇒
    ValueError (fails the boot loudly rather than silently mis-securing)."""
    auth = record.get("auth")
    if not auth:
        return AllowAll()
    name = auth if isinstance(auth, str) else auth.get("policy")
    cls = _POLICIES.get(name)
    if cls is None:
        raise ValueError(f"unknown policy {name!r}")
    return cls()
