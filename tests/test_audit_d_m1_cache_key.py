"""Audit M1 follow-up (verifier defect 2): prev_close gets its daily bars under its own 600 s key, so it never makes
the 20 s ("c", sym, "1D") candles key hot (refresh_ahead would re-download it every ~20 s). candles() itself and its
cache behaviour for charts are unchanged. Fakes only."""

from datetime import date

import pytest

from tests.test_audit_d_m1_prev_close import CAL, bars
from webapp import market_data as md

SYMBOLS = [f"STOCK{i:02d}" for i in range(10)]


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    monkeypatch.setattr(md, "equities", lambda: {})
    downloads = []

    def fake_candles(inst, tf):
        downloads.append((inst["symbol"], tf))
        return bars(), "yahoo"

    monkeypatch.setattr(md, "_candles", fake_candles)
    return downloads


def hot_candle_keys():
    return [k for k in md._cache._uses if isinstance(k, tuple) and k[0] == "c"]


@pytest.mark.unit
def test_prev_close_does_not_keep_the_1d_candles_key_hot(env):
    for s in SYMBOLS:
        value, source, _ = md.prev_close(md.instrument(s), date(2026, 11, 9), calendar=CAL)
        assert (value, source) == (24986.40, "bars (yahoo)")
    assert hot_candle_keys() == []
    assert md._cache.refresh_ahead() == 0          # nothing about to expire: no background 1D downloads
    assert len(env) == len(SYMBOLS)


@pytest.mark.unit
def test_fresh_chart_bars_are_reused_and_candles_is_unchanged(env):
    df, src = md.candles("NIFTY", "1D")             # a chart asked for them: the normal key, as before
    assert src == "yahoo" and hot_candle_keys() == [("c", "NIFTY", "1D")]
    md.prev_close(md.instrument("NIFTY"), date(2026, 11, 9), calendar=CAL)
    assert env == [("NIFTY", "1D")]                 # prev_close read the fresh bars instead of downloading again
