"""Unreliable index volume replaced by a point-in-time constituent proxy (P-02)."""

from datetime import date

import pandas as pd
import pytest

from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from tradingagents.dataflows.vendors.nse.index_volume import (
    assess_volume,
    constituent_turnover_proxy,
    is_nse_index,
    sanitize_index_ohlcv,
)
from tradingagents.dataflows.vendors.nse.indices import ConstituentStore
from tradingagents.dataflows.vendors.nse.tool_text import is_indian_instrument

DATES = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-22"])
CAL = NSECalendar({date(2026, 10, 20): "Dussehra"})


@pytest.mark.unit
def test_yahoo_style_index_volume_is_judged_unreliable():
    # The real ^NSEI values from Yahoo, 22-Oct-2026.
    a = assess_volume(pd.Series([391600, 285800, 0], index=DATES))
    assert not a.reliable and any("latest bar" in r for r in a.reasons)


@pytest.mark.unit
def test_volume_far_below_constituents_is_unreliable_even_without_zeros():
    vol = pd.Series([391600.0, 285800.0, 300000.0], index=DATES)
    constituents = pd.Series([4e8, 3.9e8, 4.1e8], index=DATES)
    a = assess_volume(vol, constituents)
    assert not a.reliable and "not the index's traded volume" in a.reasons[0]


@pytest.mark.unit
def test_a_real_volume_series_passes():
    assert assess_volume(pd.Series([1e7, 1.2e7, 0.9e7], index=DATES)).reliable


def fake_download(tickers, start, end):
    idx = pd.to_datetime(["2026-10-16", "2026-10-19", "2026-10-21", "2026-10-22"])
    close = pd.DataFrame({"A.NS": [100.0] * 4, "B.NS": [200.0] * 4, "NEW.NS": [50.0] * 4}, index=idx)
    vol = pd.DataFrame({"A.NS": [1e6] * 4, "B.NS": [2e6] * 4, "NEW.NS": [4e6] * 4}, index=idx)
    return pd.concat({"Close": close[tickers], "Volume": vol[tickers]}, axis=1)


@pytest.mark.unit
def test_proxy_uses_members_as_of_each_date(tmp_path):
    store = ConstituentStore(tmp_path)
    store.record_snapshot("NIFTY 50", date(2026, 10, 22), ["A", "B", "NEW"])
    store.add_change("NIFTY 50", date(2026, 10, 21), added=["NEW"], removed=[])
    store.set_complete_since("NIFTY 50", date(2026, 1, 1))
    proxy = constituent_turnover_proxy("NIFTY 50", date(2026, 10, 16), date(2026, 10, 22), store, fake_download)
    # Before NEW joined: A (₹1e8) + B (₹4e8) = ₹5e8 = 50 crore; after: + ₹2e8 = 70 crore.
    assert proxy.loc["2026-10-19", "turnover_cr"] == pytest.approx(50.0)
    assert proxy.loc["2026-10-22", "turnover_cr"] == pytest.approx(70.0)
    assert proxy["coverage"].eq(1.0).all() and proxy["survivorship_safe"].all()


@pytest.mark.unit
def test_sanitize_blanks_bad_volume_adds_proxy_and_reports_gaps(tmp_path):
    ohlcv = pd.DataFrame({"Close": [23146.15, 22888.95, 22687.65], "Volume": [391600, 285800, 0]},
                         index=DATES.tz_localize("Asia/Kolkata"))
    proxy = pd.DataFrame({"turnover_cr": [50.0, 50.0, 70.0], "constituent_volume": [3e6, 3e6, 7e6],
                          "coverage": [1.0] * 3, "survivorship_safe": [True] * 3}, index=DATES)
    out = sanitize_index_ohlcv(ohlcv, "NIFTY 50", CAL, proxy)
    assert out.frame["Volume"].isna().all()
    assert (out.frame["volume_source"] == "constituent_turnover_proxy").all()
    assert out.frame["volume_proxy_turnover_cr"].tolist() == [50.0, 50.0, 70.0]
    assert out.missing_sessions == [date(2026, 10, 21)]
    text = out.to_text()
    assert "UNRELIABLE" in text and "MISSING NSE sessions: 21-Oct-2026" in text


@pytest.mark.unit
def test_instrument_classification():
    assert is_nse_index("^NSEI") and not is_nse_index("RELIANCE.NS")
    assert is_indian_instrument("RELIANCE.NS") and is_indian_instrument("^NSEBANK")
    assert not is_indian_instrument("AAPL")
