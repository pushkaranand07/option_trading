"""Audit M1: the quote's previous close comes from the app's own daily bars (the last session strictly before the
quote's session), not unchecked from Yahoo's ``fast_info`` or Dhan's ``ohlc.close``.

The audit's numbers (2026-11-09, before Monday's open, after the Sunday 8 Nov Muhurat session): bars say 6 Nov =
25,030.35 and 8 Nov (Muhurat) = 24,986.40, but Yahoo's previous_close was 24,536.6 (the 5 Nov close), so the tile
showed +1.83% instead of -0.18%. All data here is recorded / built in the test: no network.
"""

from datetime import date, datetime

import pandas as pd
import pytest

from tradingagents.dataflows.vendors.nse.calendar import IST, NSECalendar
from webapp import market_data as md, signals

CAL = NSECalendar({date(2026, 11, 8): "Diwali Laxmi Pujan*", date(2026, 11, 10): "Diwali-Balipratipada"},
                  muhurat_days={date(2026, 11, 8)})

# NIFTY daily closes as the app's own 1D bars hold them (Yahoo stamps daily bars at midnight IST).
CLOSES = {
    "2026-10-30": 24400.0,   # Fri
    "2026-11-02": 24450.0,   # Mon
    "2026-11-03": 24500.0,   # Tue
    "2026-11-04": 24520.0,   # Wed
    "2026-11-05": 24536.6,   # Thu: what Yahoo wrongly called the previous close on 9 Nov
    "2026-11-06": 25030.35,  # Fri
    "2026-11-08": 24986.40,  # Sun: Muhurat session
    "2026-11-09": 25100.0,   # Mon
    "2026-11-11": 25200.0,   # Wed (10th is a holiday): today's live, unfinished bar
}


def bars(closes=CLOSES):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in closes]).tz_localize(IST)
    c = list(closes.values())
    return pd.DataFrame({"open": c, "high": c, "low": c, "close": c, "volume": [0.0] * len(c)}, index=idx)


class _FastInfo(dict):
    pass


class _Ticker:
    fi = _FastInfo(last_price=24986.40, previous_close=24536.6, open=24990.0, day_high=25010.0, day_low=24950.0)

    def __init__(self, symbol):
        self.fast_info = _Ticker.fi


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "index_lots", lambda: {})
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    monkeypatch.setattr(md.yf, "Ticker", _Ticker)
    monkeypatch.setattr(signals, "nse_calendar", lambda: CAL)
    state = {"bars": bars(), "src": "yahoo"}

    def fake_candles(inst, tf):                       # the daily-bars download (Yahoo, or Dhan when enabled)
        assert tf == "1D"
        if state["bars"] is None:
            raise md.DataError("No price data")
        return state["bars"], state["src"]

    monkeypatch.setattr(md, "_candles", fake_candles)
    return state


def at(monkeypatch, *a):
    moment = IST.localize(datetime(*a))
    monkeypatch.setattr("webapp.timeutil.now_ist", lambda: moment)
    monkeypatch.setattr("webapp.signals.now_ist", lambda: moment)


@pytest.mark.unit
def test_audit_case_after_muhurat_sunday_gives_minus_018_not_plus_183(env, monkeypatch):
    at(monkeypatch, 2026, 11, 9, 8, 30)                       # Monday before the open: the LTP is the Muhurat close
    row = md._quotes([md.instrument("NIFTY")])["NIFTY"]
    assert row["ltp"] == 24986.40
    assert row["prev_close"] == 25030.35
    assert row["change_pct"] == -0.18
    assert row["prev_close_source"].startswith("bars")
    assert "24,536.60" in row["prev_close_warning"]           # Yahoo disagreed by > 0.5%: said, not hidden
    for key in ("symbol", "name", "ltp", "prev_close", "change", "change_pct", "open", "high", "low", "source"):
        assert key in row                                     # the existing keys stay


@pytest.mark.unit
def test_dhan_quote_close_is_checked_against_the_bars_too(env, monkeypatch):
    at(monkeypatch, 2026, 11, 9, 8, 30)

    class _Dhan:
        enabled = True

        def quote(self, body):
            return {"IDX_I": {"13": {"last_price": 24986.40, "ohlc": {"open": 1, "high": 2, "low": 0.5, "close": 24536.6}}}}

    monkeypatch.setattr(md, "dhan", _Dhan())
    row = md._quotes([md.instrument("NIFTY")])["NIFTY"]
    assert row["source"] == "dhan" and row["change_pct"] == -0.18 and row["prev_close"] == 25030.35


@pytest.mark.unit
@pytest.mark.parametrize("session, expected, case", [
    (date(2026, 11, 4), 24500.0, "normal weekday"),
    (date(2026, 11, 2), 24400.0, "Monday after a weekend"),
    (date(2026, 11, 11), 25100.0, "day after a holiday"),
    (date(2026, 11, 9), 24986.40, "day after a Muhurat Sunday"),
    (date(2026, 11, 8), 25030.35, "the Muhurat session itself"),
])
def test_prev_close_is_the_last_session_strictly_before_the_quotes_session(env, session, expected, case):
    value, source, warning = md.prev_close(md.instrument("NIFTY"), session)
    assert value == expected, case
    assert source == "bars (yahoo)" and warning is None


@pytest.mark.unit
@pytest.mark.parametrize("clock, session", [
    ((2026, 11, 9, 8, 30), date(2026, 11, 8)),     # before Monday's pre-open: the Muhurat session's price
    ((2026, 11, 9, 10, 0), date(2026, 11, 9)),     # Monday in session
    ((2026, 11, 9, 18, 0), date(2026, 11, 9)),     # after the close
    ((2026, 11, 8, 11, 0), date(2026, 11, 6)),     # Muhurat Sunday before its hour
    ((2026, 11, 8, 14, 30), date(2026, 11, 8)),    # in the Muhurat hour
    ((2026, 11, 10, 11, 0), date(2026, 11, 9)),    # a weekday holiday
    ((2026, 11, 7, 11, 0), date(2026, 11, 6)),     # Saturday
])
def test_quote_session_date(env, clock, session):
    assert md.quote_session_date(IST.localize(datetime(*clock)), calendar=CAL) == session


@pytest.mark.unit
def test_vendor_value_when_no_bars_and_no_dhan(env, monkeypatch):
    at(monkeypatch, 2026, 11, 9, 8, 30)
    env["bars"] = None
    row = md._quotes([md.instrument("NIFTY")])["NIFTY"]
    assert row["prev_close"] == 24536.6 and row["prev_close_source"] == "yahoo"
    assert "prev_close_warning" not in row


@pytest.mark.unit
def test_bars_missing_the_session_fall_back_to_dhan_daily_history(env, monkeypatch):
    without_friday = {d: c for d, c in CLOSES.items() if d != "2026-11-06"}
    env["bars"] = bars(without_friday)                        # a vendor gap on the session we need
    stamps = [int(pd.Timestamp(d).tz_localize(IST).timestamp()) for d in ("2026-11-05", "2026-11-06")]
    calls = []

    class _Dhan:
        enabled = True

        def post(self, path, body):
            calls.append(path)
            return {"timestamp": stamps, "open": [1, 1], "high": [1, 1], "low": [1, 1], "close": [24536.6, 25030.35],
                    "volume": [0, 0]}

    monkeypatch.setattr(md, "dhan", _Dhan())
    value, source, warning = md.prev_close(md.instrument("NIFTY"), date(2026, 11, 8), vendor=24536.6,
                                           vendor_source="yahoo")
    assert (value, source) == (25030.35, "dhan daily")
    assert calls == ["/charts/historical"]
    assert warning and "yahoo" in warning


@pytest.mark.unit
def test_sources_within_half_a_percent_give_no_warning(env):
    value, source, warning = md.prev_close(md.instrument("NIFTY"), date(2026, 11, 9), vendor=24990.0,
                                           vendor_source="yahoo")
    assert value == 24986.40 and warning is None
