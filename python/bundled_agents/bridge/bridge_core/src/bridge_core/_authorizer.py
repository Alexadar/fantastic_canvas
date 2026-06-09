"""bridge_core authorization — base types for the per-leg, declarative rule seam.

A bridge leg is symmetric by default: once connected, either side can `call` any
agent/verb on the other. Two independent, TYPED rules govern a leg — mirrored on
the wire, enforced on the RECEIVER (a compromised peer can't bypass them):

  - an **INGRESS rule** — the inbound FILTER. `authorize(action) -> Decision`,
    consulted at the read-loop choke point before an inbound `call` dispatches.
  - an **EGRESS rule** — the outbound DECORATOR. `credential() -> token?`, consulted
    by `forward` to stamp this leg's credential onto the outbound frame ENVELOPE
    (never the dispatched payload, so the target agent never sees it).

Each rule is typed in the record (`{"type": <name>, ...config}`, with `env` naming
an env var for any secret) and resolved BY NAME from a registry — the `ingress_rules`
and `egress_rules` packages, where each rule is its own module and the package
`__init__` is the importer that registers it. Add a rule = drop a module in the
package and register its name; the engine never changes (the choke point is rule-
agnostic). A *stack* of rules is itself just a composite rule — a future registry
entry, not an engine change.

Record fields:
  - `ingress_rule` / `egress_rule` — the symmetric per-direction form (a string type
    name, or an object `{type, env, ...}`).
  - `auth` — legacy shorthand: sets BOTH directions to the same rule (so
    `auth:"password"` is a symmetric group member: checks inbound AND presents
    outbound). `ingress_rule`/`egress_rule` override it per-side.

Rules are **transitional, not invocational** — a rule is plumbing evaluated inline
as traffic passes, NOT an addressable agent. A rule that needs a dynamic decision
delegates to an agent by id (a `delegate` rule type calling `kernel.send`); the rule
itself never lives in the agent tree.
"""

from __future__ import annotations

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


class IngressRule(ABC):
    """The inbound FILTER — decides whether the peer may perform an inbound action."""

    @abstractmethod
    def authorize(self, action: Action) -> Decision: ...


class EgressRule(ABC):
    """The outbound DECORATOR — the token this leg PRESENTS on its own outbound
    `call`s (stamped on the frame envelope by `forward`). `None` ⇒ present nothing."""

    @abstractmethod
    def credential(self) -> str | None: ...


def parse_spec(spec) -> tuple[str | None, dict]:
    """Normalize a rule spec to `(type_name, config)`.

    Falsy ⇒ `(None, {})`. A bare string ⇒ `(name, {})`. An object ⇒
    `(type|policy, {…config})` — the type comes from `type` (preferred) or the
    legacy `policy`; `env` is the canonical secret-env key (legacy `token_env` is
    accepted and folded to it). Unknown keys are passed through and tolerantly
    filtered to the rule's own fields by `construct`."""
    if not spec:
        return None, {}
    if isinstance(spec, str):
        return spec, {}
    name = spec.get("type") or spec.get("policy")
    cfg: dict = {}
    for k, v in spec.items():
        if k in ("type", "policy"):
            continue
        cfg["token_env" if k == "env" else k] = v  # `env` (new) → token_env field
    return name, cfg


def construct(cls, cfg: dict):
    """Instantiate a rule dataclass, tolerantly filtering `cfg` to its own fields so
    an extra/unknown key can't crash the boot."""
    if is_dataclass(cls):
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in cfg.items() if k in allowed})
    return cls()
