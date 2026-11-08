"""Track A follow-up: trade_record.overview() is read-only and settling open trades is trade_record.refresh_open(),
which the monitor runs only while the market is open. So the server offers POST /api/trades/refresh (a write: it
needs the X-Pulse-Request header), and runs refresh_open() once at start-up in a background thread that never blocks
start-up. Without refresh_open the route answers 501; a corrupt store is 503."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from tests import test_audit_b_support as support
from tests.test_audit_b_support import HEADER
from tradingagents.dataflows.errors import VendorUnavailableError
from webapp import market_data as md, server, trade_record as tr

client, loopback = support.client, support.loopback          # the shared fixtures


@pytest.fixture
def refreshes(monkeypatch):
    calls = []

    def refresh_open(*a, **k):
        calls.append(threading.current_thread().name)
        return {"settled": 2}

    monkeypatch.setattr(tr, "refresh_open", refresh_open, raising=False)
    return calls


@pytest.mark.unit
def test_refresh_runs_refresh_open_in_the_thread_pool(client, refreshes):
    r = client.post("/api/trades/refresh", headers=HEADER)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "result": {"settled": 2}} and len(refreshes) == 1
    assert refreshes[0] != threading.main_thread().name


@pytest.mark.unit
def test_refresh_needs_the_header(client, refreshes):
    assert client.post("/api/trades/refresh").status_code == 403 and refreshes == []


@pytest.mark.unit
def test_without_refresh_open_it_is_501(client, monkeypatch):
    monkeypatch.delattr(tr, "refresh_open", raising=False)
    r = client.post("/api/trades/refresh", headers=HEADER)
    assert r.status_code == 501 and "refresh" in r.json()["detail"].lower()


@pytest.mark.unit
def test_a_corrupt_store_is_503_and_a_vendor_failure_502(client, monkeypatch):
    class StoreCorrupt(tr.TradeError):
        pass

    def corrupt():
        raise StoreCorrupt("trades.json could not be read: nothing was written.")

    monkeypatch.setattr(tr, "StoreCorrupt", StoreCorrupt, raising=False)
    monkeypatch.setattr(tr, "refresh_open", corrupt, raising=False)
    r = client.post("/api/trades/refresh", headers=HEADER)
    assert r.status_code == 503 and "nothing was written" in r.json()["detail"]

    def nse_down():
        raise VendorUnavailableError("NSE request failed after retries (HTTP 403)")

    monkeypatch.setattr(tr, "refresh_open", nse_down, raising=False)
    r = client.post("/api/trades/refresh", headers=HEADER)
    assert r.status_code == 502 and r.json() == {"detail": "NSE request failed after retries (HTTP 403)"}


@pytest.fixture
def quiet_start(monkeypatch):
    monkeypatch.setattr(md, "start_refresh_ahead", lambda *a, **k: None)
    monkeypatch.setattr(tr, "start_monitor", lambda *a, **k: None)
    monkeypatch.setattr(server, "v2_startup_check", lambda: None)


@pytest.mark.unit
def test_start_up_runs_refresh_open_once_in_the_background_without_waiting(loopback, quiet_start, monkeypatch):
    release, ran = threading.Event(), []

    def slow_refresh():
        ran.append(threading.current_thread())
        release.wait(10)                                                     # still settling while the page loads

    monkeypatch.setattr(tr, "refresh_open", slow_refresh, raising=False)
    started = time.perf_counter()
    with TestClient(server.app, base_url="http://127.0.0.1") as c:
        assert c.get("/api/latency").status_code == 200
        assert time.perf_counter() - started < 5                             # start-up did not wait for it
        deadline = time.time() + 5
        while not ran and time.time() < deadline:
            time.sleep(0.01)
        release.set()
    assert len(ran) == 1 and ran[0].daemon and ran[0] is not threading.main_thread()


@pytest.mark.unit
def test_a_failing_start_up_refresh_is_logged_not_raised(loopback, quiet_start, monkeypatch, caplog):
    done = threading.Event()

    def broken():
        try:
            raise RuntimeError("chain unavailable")
        finally:
            done.set()

    monkeypatch.setattr(tr, "refresh_open", broken, raising=False)
    with TestClient(server.app, base_url="http://127.0.0.1") as c:
        assert done.wait(5)
        time.sleep(0.1)
        assert c.get("/api/latency").status_code == 200
    assert any("refresh" in rec.getMessage().lower() and rec.exc_info for rec in caplog.records)
