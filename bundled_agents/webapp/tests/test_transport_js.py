"""Snapshot test for the inlined transport.js IIFE."""

from __future__ import annotations

from webapp._transport_js import TRANSPORT_JS


def test_iife_format():
    s = TRANSPORT_JS
    assert s.startswith("(function ()")
    assert s.rstrip().endswith("})();")


def test_exports_fantastic_transport():
    assert "window.fantastic_transport" in TRANSPORT_JS


def test_has_dispatcher_proxy():
    assert "dispatcher" in TRANSPORT_JS
    assert "Proxy" in TRANSPORT_JS


def test_has_watch_unwatch():
    assert "watch" in TRANSPORT_JS
    assert "unwatch" in TRANSPORT_JS


def test_has_event_listeners():
    assert "on(" in TRANSPORT_JS or "function on" in TRANSPORT_JS
