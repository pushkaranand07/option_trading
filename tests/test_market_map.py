"""Market Map page data: event impact windows and detected events."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import market_map as mm  # noqa: E402


def frame(n=80):
    idx = pd.bdate_range("2021-01-01", periods=n)
    nifty = pd.Series(100.0, index=idx)
    nifty.iloc[41:] = 110.0                                  # +10% jump on session 41 (a Monday)
    lot = pd.Series(50.0, index=idx)
    lot.iloc[60:] = 25.0
    return pd.DataFrame({
        "nifty": nifty, "vix": 15.0, "nifty_opt_val": np.where(np.arange(n) < 41, 100.0, 150.0),
        "bn_opt_val": 50.0, "nifty_pcr": 1.0, "fii_long": 0.4, "regime": "calm", "nifty_lot": lot, "bn_lot": 15.0,
    }, index=idx)


@pytest.mark.unit
def test_impact_is_measured_from_the_first_session_on_or_after_the_date():
    df = frame()
    monday = df.index[41]
    assert monday.weekday() == 0                             # 2021-01-01 is a Friday: session 41 is a Monday
    out = mm.impact(df, (monday - pd.Timedelta(days=2)).strftime("%Y-%m-%d"))   # the Saturday before
    assert out["session"] == monday.strftime("%Y-%m-%d")
    assert out["nifty_day"] == pytest.approx(0.10)
    assert out["opt_before"] == 100.0 and out["opt_after"] == 150.0
    assert out["regime"] == "calm"
    assert out["bn_opt_before"] == out["bn_opt_after"] == 50.0


@pytest.mark.unit
def test_impact_needs_a_month_of_history_and_a_session_after():
    df = frame()
    assert mm.impact(df, df.index[5].strftime("%Y-%m-%d")) is None
    assert mm.impact(df, "2030-01-01") is None


@pytest.mark.unit
def test_detected_events_include_the_jump_and_the_lot_change():
    ev = mm.detected_events(frame())
    titles = [e["title"] for e in ev]
    assert "NIFTY +9.5% day" in titles                      # log return of +10%
    assert "NIFTY lot size 50 → 25" in titles
    assert not any("BANKNIFTY lot" in t for t in titles)


@pytest.mark.unit
def test_page_embeds_the_data_safely():
    html = mm.render({"events": [{"title": "</script><b>x"}], "log": []})
    assert html.startswith("<!doctype html>") and "/*__DATA__*/" not in html
    assert "</script><b>x" not in html and r"<\/script><b>x" in html
