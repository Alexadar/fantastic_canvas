"""bridge_core — direct unit tests of the shared engine primitives (the
transport-agnostic surface; full forward/round-trip coverage lives in the
kernel_bridge + cloud_bridge suites that drive it through MemoryTransport)."""

from __future__ import annotations

import pytest

from bridge_core import core
from bridge_core._authorizer import Action
from bridge_core.egress_rules import Silent, resolve_egress
from bridge_core.egress_rules.password import Password as EgressPassword
from bridge_core.ingress_rules import AllowAll, DenyInbound, resolve_ingress
from bridge_core.ingress_rules.password import Password as IngressPassword


async def _noop_build(kind, rec, kernel, st):  # pragma: no cover - not invoked here
    raise AssertionError("build_transport should not be called in these tests")


def _verbs():
    return core.make_verbs(
        build_transport=_noop_build,
        sentence="test bridge",
        reflect_fields=lambda rec, st: {"x": 1},
        default_kind="ws",
    )


def test_make_verbs_builds_the_six_verbs():
    verbs = _verbs()
    assert set(verbs) == {
        "reflect",
        "boot",
        "reconnect",
        "forward",
        "watch_remote",
        "unwatch_remote",
    }


def test_next_corr_namespaces_by_agent_id():
    core._bridges.clear()
    sa = core._state("a")
    sb = core._state("b")
    assert core._next_corr("a", sa) == "a:1"
    assert core._next_corr("a", sa) == "a:2"
    assert core._next_corr("b", sb) == "b:1"  # independent counter per agent
    core._bridges.clear()


async def test_dispatch_unknown_type_errors():
    verbs = _verbs()
    out = await core.dispatch(verbs, "id", {"type": "nope"}, kernel=None)
    assert "unknown type" in out["error"]


async def test_forward_before_boot_reports_not_connected():
    core._bridges.clear()
    verbs = _verbs()
    out = await verbs["forward"](
        "id", {"type": "forward", "target": "t", "payload": {}}, kernel=None
    )
    assert "not connected" in out["error"]
    core._bridges.clear()


# ─── ingress rules (the inbound FILTER) ─────────────────────────


def _call(token=None):
    # the token rides the frame envelope (Action.token), NOT the dispatched payload
    return Action("call", "t", "reflect", {"type": "reflect"}, token=token)


def test_allow_all_permits_call_and_watch():
    a = AllowAll()
    assert a.authorize(_call()).allowed
    assert a.authorize(Action("watch", "t", "watch", {})).allowed


def test_deny_inbound_refuses_call_allows_watch():
    a = DenyInbound()
    d = a.authorize(_call())
    assert not d.allowed and d.reason  # carries a reason for the unauthorized reply
    # watch/unwatch are already ignored by the read loop → not gated here.
    assert a.authorize(Action("watch", "t", "watch", {})).allowed


def test_resolve_ingress_absent_is_allow_all():
    assert isinstance(resolve_ingress({}), AllowAll)  # back-compat no-op
    assert isinstance(resolve_ingress({"auth": ""}), AllowAll)
    assert isinstance(resolve_ingress({"ingress_rule": None}), AllowAll)


def test_resolve_ingress_string_and_object_forms():
    assert isinstance(resolve_ingress({"auth": "deny_inbound"}), DenyInbound)
    # the symmetric per-direction field overrides the `auth` shorthand
    assert isinstance(
        resolve_ingress({"auth": "allow_all", "ingress_rule": "deny_inbound"}),
        DenyInbound,
    )
    # object form, both `type` (new) and `policy` (legacy) spellings
    assert isinstance(
        resolve_ingress({"ingress_rule": {"type": "deny_inbound"}}), DenyInbound
    )
    assert isinstance(
        resolve_ingress({"auth": {"policy": "deny_inbound"}}), DenyInbound
    )


def test_resolve_ingress_unknown_type_raises():
    with pytest.raises(ValueError):
        resolve_ingress({"ingress_rule": "nope"})


# ─── password rule, both sides (kernel-group shared secret) ─────


def test_ingress_password_checks_envelope_token(monkeypatch):
    monkeypatch.setenv("FANTASTIC_GROUP_TOKEN", "s3cret")
    p = IngressPassword()
    assert p.authorize(_call("s3cret")).allowed
    assert not p.authorize(_call("nope")).allowed
    assert not p.authorize(_call(None)).allowed  # no auth_token at all
    # watch/unwatch are not gated (denied-by-omission in the read loop)
    assert p.authorize(Action("watch", "t", "watch", {})).allowed


def test_ingress_password_fails_closed_when_token_unset(monkeypatch):
    monkeypatch.delenv("FANTASTIC_GROUP_TOKEN", raising=False)
    d = IngressPassword().authorize(_call("anything"))
    assert not d.allowed and "unset" in d.reason  # misconfig must not allow


def test_egress_password_presents_token(monkeypatch):
    monkeypatch.setenv("MY_GROUP", "abc")
    assert EgressPassword(token_env="MY_GROUP").credential() == "abc"
    monkeypatch.delenv("MY_GROUP", raising=False)
    assert EgressPassword(token_env="MY_GROUP").credential() is None  # unset ⇒ nothing


def test_resolve_egress_threads_env_and_defaults_silent():
    # `auth:"password"` is symmetric: egress presents (the legacy shorthand)
    assert isinstance(resolve_egress({"auth": "password"}), EgressPassword)
    # `env` (new) and `token_env` (legacy) both reach the rule's field
    assert (
        resolve_egress(
            {"egress_rule": {"type": "password", "env": "MY_GROUP"}}
        ).token_env
        == "MY_GROUP"
    )
    assert (
        resolve_egress(
            {"auth": {"policy": "password", "token_env": "MY_GROUP"}}
        ).token_env
        == "MY_GROUP"
    )
    # inbound-only names + absent ⇒ Silent (present nothing) — back-compat wire shape
    assert isinstance(resolve_egress({"auth": "deny_inbound"}), Silent)
    assert isinstance(resolve_egress({}), Silent)


def test_asymmetric_ingress_egress():
    # a hub: refuse inbound, still present a group token outbound
    rec = {
        "ingress_rule": "deny_inbound",
        "egress_rule": {"type": "password", "env": "MY_GROUP"},
    }
    assert isinstance(resolve_ingress(rec), DenyInbound)
    assert isinstance(resolve_egress(rec), EgressPassword)


def test_resolve_tolerates_unknown_config_keys():
    a = resolve_ingress({"ingress_rule": {"type": "password", "bogus": 1}})
    assert isinstance(a, IngressPassword) and a.token_env == "FANTASTIC_GROUP_TOKEN"
