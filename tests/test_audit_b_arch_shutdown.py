"""ARCH follow-up: the lifespan shuts down what it started. After ``yield`` it calls the stop hooks
``market_data.stop_refresh_ahead()`` and ``trade_record.stop_monitor()`` when those modules have them (they belong to
other tracks; today neither exists), and it leaves no non-daemon thread behind: both background threads are daemon
threads, so they never keep the process alive on shutdown."""

import threading

import pytest
from fastapi.testclient import TestClient

from tests import test_audit_b_support as support
from webapp import market_data as md, server, trade_record as tr

client, loopback = support.client, support.loopback          # the shared fixtures


@pytest.fixture
def no_starts(monkeypatch):
    monkeypatch.setattr(md, "start_refresh_ahead", lambda *a, **k: None)
    monkeypatch.setattr(tr, "start_monitor", lambda *a, **k: None)
    monkeypatch.setattr(server, "v2_startup_check", lambda: None)
    monkeypatch.setattr(tr, "refresh_open", lambda *a, **k: None, raising=False)


@pytest.mark.unit
def test_shutdown_calls_the_stop_hooks_when_present(loopback, no_starts, monkeypatch):
    stopped = []
    monkeypatch.setattr(md, "stop_refresh_ahead", lambda: stopped.append("refresh-ahead"), raising=False)
    monkeypatch.setattr(tr, "stop_monitor", lambda: stopped.append("trade-monitor"), raising=False)
    with TestClient(server.app, base_url="http://127.0.0.1") as c:
        c.get("/api/latency")
        assert stopped == []                                                 # not before shutdown
    assert sorted(stopped) == ["refresh-ahead", "trade-monitor"]


@pytest.mark.unit
def test_shutdown_without_hooks_or_with_a_failing_hook_is_clean(loopback, no_starts, monkeypatch):
    monkeypatch.delattr(md, "stop_refresh_ahead", raising=False)

    def broken():
        raise RuntimeError("stop failed")

    monkeypatch.setattr(tr, "stop_monitor", broken, raising=False)
    before = {t.ident for t in threading.enumerate() if not t.daemon}
    with TestClient(server.app, base_url="http://127.0.0.1") as c:
        c.get("/api/latency")
    after = {t.ident for t in threading.enumerate() if not t.daemon and t.is_alive()}
    assert after <= before                                                   # nothing non-daemon left behind


class _Thread:
    made = []

    def __init__(self, *a, daemon=None, **k):
        _Thread.made.append(daemon)

    def start(self):
        pass


@pytest.mark.unit
def test_the_background_threads_are_daemon_threads(monkeypatch):
    _Thread.made.clear()
    monkeypatch.setattr(md, "_refresher", None)
    monkeypatch.setattr(tr, "_monitor_started", False)
    monkeypatch.setattr(md.threading, "Thread", _Thread)
    md.start_refresh_ahead()
    tr.start_monitor()
    assert _Thread.made == [True, True]
