"""Web app candles: when Yahoo is unreachable the last good bars are served (and survive a restart), not an error."""

import pandas as pd
import pytest

from webapp import market_data as md


class _Ticker:
    frame = pd.DataFrame()
    fail = False

    def __init__(self, symbol):
        pass

    def history(self, **kw):
        if _Ticker.fail:
            raise ConnectionError("getaddrinfo failed")
        return _Ticker.frame


@pytest.fixture
def yahoo(monkeypatch, tmp_path):
    monkeypatch.setattr(md, "LAST_GOOD_DIR", tmp_path)
    monkeypatch.setattr(md, "_good", {})
    monkeypatch.setattr(md, "_good_saved", {})
    monkeypatch.setattr(md.yf, "Ticker", _Ticker)
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    idx = pd.date_range("2026-10-23 09:15", periods=3, freq="5min", tz=md.IST)
    _Ticker.frame = pd.DataFrame({"Open": [1.0, 2, 3], "High": [2.0, 3, 4], "Low": [0.5, 1, 2], "Close": [1.5, 2.5, 3.5],
                                  "Volume": [10.0, 20, 30]}, index=idx)
    _Ticker.fail = False
    return _Ticker


@pytest.mark.unit
def test_yahoo_down_serves_the_last_good_bars_labelled_as_saved(yahoo):
    inst = md.instrument("NIFTY")
    df, src = md._candles(inst, "5m")
    assert src == "yahoo" and len(df) == 3
    yahoo.fail = True
    again, src = md._candles(inst, "5m")
    assert src.startswith("saved (last bar 23-Oct 09:25") and again["close"].iloc[-1] == 3.5
    md._good.clear()                                   # a server restart: the copy on disk is used
    assert md._candles(inst, "5m")[1].startswith("saved")
    yahoo.frame = pd.DataFrame()
    yahoo.fail = False                                 # Yahoo answers but with nothing ("possibly delisted")
    assert md._candles(inst, "5m")[1].startswith("saved")


@pytest.mark.unit
def test_nothing_saved_and_yahoo_down_is_a_clear_error(yahoo):
    yahoo.fail = True
    with pytest.raises(md.DataError, match="unreachable"):
        md._candles(md.instrument("BANKNIFTY"), "5m")
