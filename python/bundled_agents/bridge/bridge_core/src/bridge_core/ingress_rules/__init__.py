"""ingress_rules — the inbound-FILTER rule registry (the "upper importer").

Each ingress rule is its own module here; this package registers them BY NAME in
`REGISTRY`. The read loop resolves a leg's rule via `resolve_ingress(record)` and
consults it at the single inbound-`call` choke point. Add a rule = drop a module +
one `REGISTRY` line; the engine never changes.
"""

from __future__ import annotations

from bridge_core._authorizer import IngressRule, construct, parse_spec
from bridge_core.ingress_rules.allow_all import AllowAll
from bridge_core.ingress_rules.deny_inbound import DenyInbound
from bridge_core.ingress_rules.password import Password

# name → ingress rule class. New ingress rule types register HERE.
REGISTRY: dict[str, type[IngressRule]] = {
    "allow_all": AllowAll,
    "deny_inbound": DenyInbound,
    "password": Password,
}


def resolve_ingress(record: dict) -> IngressRule:
    """Resolve the leg's INGRESS rule: `ingress_rule` if the record carries it, else
    the legacy `auth` shorthand. Absent ⇒ `AllowAll` (back-compat no-op). Unknown
    type ⇒ `ValueError` (fail the boot loudly rather than silently mis-securing)."""
    spec = record["ingress_rule"] if "ingress_rule" in record else record.get("auth")
    name, cfg = parse_spec(spec)
    if name is None:
        return AllowAll()
    cls = REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"unknown ingress rule type {name!r}")
    return construct(cls, cfg)


__all__ = ["REGISTRY", "AllowAll", "DenyInbound", "Password", "resolve_ingress"]
