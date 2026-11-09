"""Fixes from the final diff review (audit 2026-11).

1. The Dhan guard held its lock for the whole HTTP call, so one slow download blocked every other Dhan request; the
   one-per-second rule only needs to space the STARTS. It also accepted http:// and other ports, and let requests
   follow redirects (so what was checked was not necessarily what was fetched).
2. A paper trade that expired after the market closed stayed "open" until the next session: the monitor only ran
   while the market was open. Now one pass a day after 15:30 settles open trades past their expiry, and otherwise a
   closed market still reads nothing.
"""

import threading
from datetime import datetime

import pytest
import pytz

from tests.test_ui_regressions import pytestmark as _needs_node, render
from webapp import dhan_guard as g, signals, trade_record as tr

IST = pytz.timezone("Asia/Kolkata")


# ---------------------------------------------------------------- 1. the guard


@pytest.fixture
def guard(monkeypatch, tmp_path):
    monkeypatch.setattr(g, "LOG", tmp_path / "dhan_calls.log")
    monkeypatch.setattr(g, "_last", 0.0)
    return g


@pytest.mark.unit
def test_a_slow_dhan_request_does_not_block_the_next_one(guard, monkeypatch):
    started, release, order = threading.Event(), threading.Event(), []

    class R:
        status_code = 200

    def transport(method, url, **kw):
        order.append(url)
        if url.endswith("api-scrip-master.csv"):
            started.set()
            release.wait(5)                                     # a slow download, still in flight
        return R()

    monkeypatch.setattr(g.requests, "request", transport)
    monkeypatch.setattr(g, "MIN_INTERVAL", 0.05)
    slow = threading.Thread(target=g.request, args=("GET", "https://images.dhan.co/api-data/api-scrip-master.csv"))
    slow.start()
    assert started.wait(2)
    done = threading.Event()
    fast = threading.Thread(target=lambda: (g.request("POST", "/marketfeed/ltp", token="t", client_id="c"), done.set()))
    fast.start()
    assert done.wait(2), "the quote waited for the slow download to finish"
    release.set()
    slow.join(2)
    fast.join(2)


@pytest.mark.unit
def test_starts_are_still_spaced_one_interval_apart(guard, monkeypatch):
    clock, waits, sent = {"t": 100.0}, [], []
    monkeypatch.setattr(g, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(g, "_sleep", lambda s: waits.append(s) or clock.__setitem__("t", clock["t"] + s))
    monkeypatch.setattr(g.requests, "request", lambda m, u, **kw: sent.append(u) or type("R", (), {"status_code": 200})())
    for _ in range(3):
        g.request("POST", "/marketfeed/ltp", token="t", client_id="c")
    assert len(sent) == 3 and len(waits) == 2 and all(w >= g.MIN_INTERVAL - 1e-9 for w in waits)


@pytest.mark.unit
@pytest.mark.parametrize("url", ["http://api.dhan.co/v2/marketfeed/ltp", "https://api.dhan.co:8443/v2/marketfeed/ltp",
                                 "http://images.dhan.co/api-data/api-scrip-master.csv"])
def test_only_https_on_the_default_port_is_allowed(guard, monkeypatch, url):
    sent = []
    monkeypatch.setattr(g.requests, "request", lambda m, u, **kw: sent.append(u))
    with pytest.raises(g.DhanAccountAccessBlocked):
        g.request("POST" if "marketfeed" in url else "GET", url, token="t", client_id="c")
    assert sent == []


@pytest.mark.unit
def test_redirects_are_not_followed(guard, monkeypatch):
    seen = {}

    def transport(m, u, **kw):
        seen.update(kw)
        return type("R", (), {"status_code": 200})()

    monkeypatch.setattr(g.requests, "request", transport)
    monkeypatch.setattr(g, "_sleep", lambda s: None)
    g.request("POST", "/marketfeed/ltp", token="t", client_id="c")
    assert seen.get("allow_redirects") is False


# ---------------------------------------------------------------- 2. settling after the close


def _store(tmp_path, monkeypatch, rows):
    import json

    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_monitor", {"running": False, "last_ok_at": None, "last_error": None, "fail_count": 0})
    monkeypatch.setattr(tr, "_after_close_day", None, raising=False)
    tr.STORE.write_text(json.dumps(rows), encoding="utf-8")


@pytest.mark.unit
def test_one_pass_after_the_close_settles_trades_past_expiry(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [{"id": "x", "status": "open", "expiry": "09-Nov-2026", "taken_at": "2026-11-09 10:00",
                                    "symbol": "NIFTY", "legs": []}])
    monkeypatch.setattr(signals, "market_open", lambda *a: False)
    monkeypatch.setattr(tr, "_clock", lambda: IST.localize(datetime(2026, 11, 9, 16, 0)))
    calls = []
    monkeypatch.setattr(tr, "refresh_open", lambda *a, **k: calls.append(1))
    assert tr._monitor_tick() is True and calls == [1]
    assert tr._monitor_tick() is True and calls == [1]              # once a day: later ticks read nothing


@pytest.mark.unit
def test_after_the_close_nothing_happens_without_an_expired_open_trade(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [{"id": "x", "status": "open", "expiry": "17-Nov-2026", "taken_at": "2026-11-09 10:00",
                                    "symbol": "NIFTY", "legs": []}])
    monkeypatch.setattr(signals, "market_open", lambda *a: False)
    monkeypatch.setattr(tr, "_clock", lambda: IST.localize(datetime(2026, 11, 9, 16, 0)))
    monkeypatch.setattr(tr, "refresh_open", lambda *a, **k: pytest.fail("nothing to settle"))
    assert tr._monitor_tick() is True


@pytest.mark.unit
def test_before_the_close_a_closed_market_still_reads_nothing(tmp_path, monkeypatch):
    _store(tmp_path, monkeypatch, [{"id": "x", "status": "open", "expiry": "06-Nov-2026"}])
    monkeypatch.setattr(signals, "market_open", lambda *a: False)
    monkeypatch.setattr(tr, "_clock", lambda: IST.localize(datetime(2026, 11, 8, 11, 0)))   # a Sunday morning
    monkeypatch.setattr(tr, "_load", lambda: pytest.fail("read the store"))
    assert tr._monitor_tick() is True


# ---------------------------------------------------------------- 3. small leftovers


@pytest.mark.unit
@_needs_node
def test_a_422_shows_the_validation_message_not_just_the_status():
    js = ("fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ['body', 'candidate'], "
          "msg: 'Field required' }] }) }); api('/api/trades', { method: 'POST' }).then(() => 'ok', (e) => e.message)")
    assert render(js) == "Field required"


@pytest.mark.unit
def test_an_unavailable_expiry_list_is_logged_not_swallowed(monkeypatch, caplog):
    import logging

    from webapp import option_chain as oc

    def down(symbol):
        raise RuntimeError("NSE down")

    monkeypatch.setattr(oc, "expiries", down)
    with caplog.at_level(logging.WARNING, logger=oc.logger.name):
        assert oc.valid_expiries("NIFTY") == []
    assert any("unavailable" in r.getMessage() and r.exc_info for r in caplog.records)
