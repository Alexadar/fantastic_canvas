"""`silent` — the default egress rule: present no credential (today's wire shape)."""

from __future__ import annotations

from dataclasses import dataclass

from bridge_core._authorizer import EgressRule


@dataclass(frozen=True)
class Silent(EgressRule):
    """Attach nothing to outbound calls — the back-compat default and what every
    non-credential-bearing policy (allow_all / deny_inbound) presents."""

    def credential(self) -> str | None:
        return None
