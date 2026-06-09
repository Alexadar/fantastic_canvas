"""`deny_inbound` — one-way / hub→spoke push: refuse every inbound `call`."""

from __future__ import annotations

from dataclasses import dataclass

from bridge_core._authorizer import ALLOW, Action, Decision, IngressRule


@dataclass(frozen=True)
class DenyInbound(IngressRule):
    """Refuse every inbound `call` (the peer can't `call`/`reflect` us). Inbound
    `watch`/`unwatch` are already ignored by the read loop ⇒ denied-by-omission."""

    def authorize(self, action: Action) -> Decision:
        if action.kind == "call":
            return Decision(False, "inbound calls denied by policy")
        return ALLOW
