"""Audit M1 follow-up (verifier defect 1): a cold /api/quotes resolves the previous closes in parallel, so N symbols
cost about one daily-bars download, not N. Fakes only: a 0.2 s daily download, an instant Yahoo quote."""

import time
from datetime import datetime

import pytest

from tests.test_audit_d_m1_prev_close import CAL, bars
from tradingagents.dataflows.vendors.nse.calendar import IST
from webapp import market_data as md, signals

SYMBOLS = [f"STOCK{i:02d}" for i in range(30)]


class _Ticker:
    def __init__(self, symbol):
        self.fast_info = {"last_price": 24986.40, "previous_close": 24536.6, "open": 1.0, "day_high": 2.0,
                          "day_low": 0.5}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    monkeypatch.setattr(md, "equities", lambda: {})
    monkeypatch.setattr(md.yf, "Ticker", _Ticker)
    monkeypatch.setattr(signals, "nse_calendar", lambda: CAL)
    moment = IST.localize(datetime(2026, 11, 9, 8, 30))
    monkeypatch.setattr("webapp.timeutil.now_ist", lambda: moment)
    downloads = []

    def slow_candles(inst, tf):
        downloads.append(inst["symbol"])
        time.sleep(0.2)                                     # one 2-year daily download
        return bars(), "yahoo"

    monkeypatch.setattr(md, "_candles", slow_candles)
    return downloads


@pytest.mark.unit
def test_cold_quotes_for_30_symbols_cost_about_one_download(env):
    started = time.monotonic()
    got = md.quotes(SYMBOLS)
    took = time.monotonic() - started
    print(f"cold quotes for {len(SYMBOLS)} symbols: {took:.2f} s")
    assert took < 1.5, f"cold quotes took {took:.2f} s"
    assert sorted(env) == sorted(SYMBOLS)                   # each symbol's bars fetched once
    # Identical to the serial computation, symbol by symbol.
    md._cache = md._TTLCache()
    for s in SYMBOLS:
        inst = md.instrument(s)
        serial = md._quote_row(inst, 24986.40, 24536.6, {"open": 1.0, "high": 2.0, "low": 0.5}, "yahoo",
                               checked=md.prev_close(inst, md.quote_session_date(), vendor=24536.6,
                                                     vendor_source="yahoo"))
        assert got[s] == serial
        assert got[s]["change_pct"] == -0.18
