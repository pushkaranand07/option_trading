"""Audit M1 follow-up (verifier defect 3): NaN, inf, 0 or a negative previous close counts as missing. A quote row
never carries NaN; with no valid previous close it says so (prev_close None, a warning) and stays JSON-safe."""

import json
import math
from datetime import date, datetime

import pytest

from tests.test_audit_d_m1_prev_close import CAL, bars
from tradingagents.dataflows.vendors.nse.calendar import IST
from webapp import market_data as md, signals

BAD = [float("nan"), float("inf"), float("-inf"), 0.0, -5.0]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "index_lots", lambda: {})
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    monkeypatch.setattr(signals, "nse_calendar", lambda: CAL)
    moment = IST.localize(datetime(2026, 11, 9, 8, 30))
    monkeypatch.setattr("webapp.timeutil.now_ist", lambda: moment)
    state = {"bars": bars()}

    def fake_candles(inst, tf):
        if state["bars"] is None:
            raise md.DataError("No price data")
        return state["bars"], "yahoo"

    monkeypatch.setattr(md, "_candles", fake_candles)
    return state


def yahoo(monkeypatch, prev):
    fi = {"last_price": 24986.40, "previous_close": prev, "open": 1.0, "day_high": 2.0, "day_low": 0.5}
    monkeypatch.setattr(md.yf, "Ticker", lambda s: type("T", (), {"fast_info": fi})())


@pytest.mark.unit
@pytest.mark.parametrize("bad", BAD)
def test_a_bad_vendor_value_is_ignored_when_the_bars_have_the_close(env, bad):
    value, source, warning = md.prev_close(md.instrument("NIFTY"), date(2026, 11, 8), vendor=bad,
                                           vendor_source="yahoo")
    assert (value, source, warning) == (25030.35, "bars (yahoo)", None)


@pytest.mark.unit
@pytest.mark.parametrize("bad", BAD)
def test_no_valid_previous_close_anywhere_gives_a_json_safe_row(env, monkeypatch, bad):
    env["bars"] = None
    yahoo(monkeypatch, bad)
    row = md._quotes([md.instrument("NIFTY")])["NIFTY"]
    json.dumps(row, allow_nan=False)                         # raises on NaN / inf
    assert row["prev_close"] is None and row["change"] == 0.0 and row["change_pct"] == 0.0
    assert row["ltp"] == 24986.40
    assert "no valid previous close" in row["prev_close_warning"].lower()
    assert not any(isinstance(v, float) and not math.isfinite(v) for v in row.values())


@pytest.mark.unit
def test_inf_in_the_bars_is_not_a_close(env):
    df = bars()
    df.loc[df.index[5], "close"] = float("inf")             # the 6 Nov bar
    env["bars"] = df
    value, source, _ = md.prev_close(md.instrument("NIFTY"), date(2026, 11, 8), vendor=24536.6, vendor_source="yahoo")
    assert (value, source) == (24536.6, "yahoo")
