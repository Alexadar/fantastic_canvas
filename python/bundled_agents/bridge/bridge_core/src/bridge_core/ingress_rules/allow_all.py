"""`allow_all` — the default ingress rule: full symmetric duplex, a true no-op."""

from __future__ import annotations

from dataclasses import dataclass

from bridge_core._authorizer import ALLOW, Action, Decision, IngressRule


@dataclass(frozen=True)
class AllowAll(IngressRule):
    """Permit every inbound action. The engine default (absent rule ⇒ this)."""

    def authorize(self, action: Action) -> Decision:
        return ALLOW
