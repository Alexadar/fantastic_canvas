"""bridge_core — direct unit tests of the shared engine primitives (the
transport-agnostic surface; full forward/round-trip coverage lives in the
kernel_bridge + cloud_bridge suites that drive it through MemoryTransport)."""

from __future__ import annotations

import pytest

from bridge_core import core
from bridge_core._authorizer import Action, AllowAll, DenyInbound, make_authorizer


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


# ─── authorization seam (the `auth` policy) ─────────────────────


def test_allow_all_permits_call_and_watch():
    a = AllowAll()
    assert a.authorize(Action("call", "t", "reflect", {})).allowed
    assert a.authorize(Action("watch", "t", "watch", {})).allowed


def test_deny_inbound_refuses_call_allows_watch():
    a = DenyInbound()
    d = a.authorize(Action("call", "t", "reflect", {"type": "reflect"}))
    assert not d.allowed and d.reason  # carries a reason for the unauthorized reply
    # watch/unwatch are already ignored by the read loop → not gated here.
    assert a.authorize(Action("watch", "t", "watch", {})).allowed


def test_make_authorizer_absent_is_allow_all():
    assert isinstance(make_authorizer({}), AllowAll)  # back-compat no-op
    assert isinstance(make_authorizer({"auth": ""}), AllowAll)


def test_make_authorizer_string_policy():
    assert isinstance(make_authorizer({"auth": "deny_inbound"}), DenyInbound)
    assert isinstance(make_authorizer({"auth": "allow_all"}), AllowAll)


def test_make_authorizer_object_form_is_forward_compat():
    assert isinstance(
        make_authorizer({"auth": {"policy": "deny_inbound"}}), DenyInbound
    )


def test_make_authorizer_unknown_policy_raises():
    with pytest.raises(ValueError):
        make_authorizer({"auth": "nope"})
