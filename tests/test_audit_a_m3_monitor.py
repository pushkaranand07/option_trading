"""Audit M3: the trade-record monitor swallowed every exception (``except Exception: pass``), so a monitor that
failed every minute looked healthy. Now each failure is logged with its traceback, consecutive failures are
counted, and ``monitor_status()`` reports them. The loop body is ``_monitor_tick()``, driven here without threads
or sleeps; ``start_monitor()`` starts the thread once, also when called from several threads at once."""

import logging
import threading
from types import SimpleNamespace

import pytest

from tests.test_trade_record import RESULT
from webapp import signals, trade_record as tr


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    monkeypatch.setattr(signals, "market_open", lambda *a: True)
    monkeypatch.setattr(tr, "_monitor", dict(tr._monitor))     # a fresh status per test
    tr.take(RESULT)


def boom(*a, **k):
    raise RuntimeError("NSE said no")


@pytest.mark.unit
def test_a_failing_check_is_logged_with_its_traceback_and_counted(monkeypatch, caplog):
    monkeypatch.setattr(tr, "refresh_open", boom)
    with caplog.at_level(logging.ERROR, logger=tr.logger.name):
        assert tr._monitor_tick() is False
        assert tr._monitor_tick() is False
    s = tr.monitor_status()
    assert s["fail_count"] == 2 and "NSE said no" in s["last_error"] and s["last_ok_at"] is None
    failed = [r for r in caplog.records if r.exc_info]
    assert len(failed) == 2 and "NSE said no" in str(failed[0].exc_info[1])


@pytest.mark.unit
def test_a_good_check_resets_the_count(monkeypatch):
    monkeypatch.setattr(tr, "refresh_open", boom)
    tr._monitor_tick()
    calls = []
    monkeypatch.setattr(tr, "refresh_open", lambda *a, **k: calls.append(1))
    assert tr._monitor_tick() is True and calls == [1]
    s = tr.monitor_status()
    assert s["fail_count"] == 0 and s["last_error"] is None and s["last_ok_at"]


@pytest.mark.unit
def test_a_closed_market_checks_nothing_and_is_not_a_failure(monkeypatch):
    monkeypatch.setattr(signals, "market_open", lambda *a: False)
    monkeypatch.setattr(tr, "refresh_open", boom)
    assert tr._monitor_tick() is True and tr.monitor_status()["fail_count"] == 0


@pytest.mark.unit
def test_monitor_status_has_the_agreed_keys():
    assert set(tr.monitor_status()) == {"running", "last_ok_at", "last_error", "fail_count"}


@pytest.mark.unit
def test_start_monitor_starts_one_thread_even_when_called_from_many_at_once(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(tr, "_monitor_started", False)
    monkeypatch.setattr(tr, "threading", SimpleNamespace(Thread=FakeThread, Lock=threading.Lock, Event=threading.Event))
    gate = threading.Barrier(8)

    def call():
        gate.wait()
        tr.start_monitor()
    callers = [threading.Thread(target=call) for _ in range(8)]   # the real Thread: only trade_record's is faked
    for c in callers:
        c.start()
    for c in callers:
        c.join(10)
    assert len(started) == 1 and tr._monitor_started is True
