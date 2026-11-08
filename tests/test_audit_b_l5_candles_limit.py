"""L5: /api/candles took any ``limit`` (0 or a negative number silently returned every bar). Now 1 <= limit <= 5000,
anything else is 422."""

import pandas as pd
import pytest

from tests import test_audit_b_support as support
from webapp import market_data as md, signals

client, loopback = support.client, support.loopback          # the shared fixtures


@pytest.fixture
def bars(monkeypatch):
    idx = pd.date_range("2026-11-09 09:15", periods=10, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100}, index=idx)
    monkeypatch.setattr(md, "candles", lambda symbol, tf: (df, "yahoo"))
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: False)
    return df


@pytest.mark.unit
@pytest.mark.parametrize("limit", [0, -1, 5001, 10**9])
def test_an_out_of_range_limit_is_422(client, bars, limit):
    r = client.get("/api/candles/NIFTY", params={"limit": limit})
    assert r.status_code == 422, r.text


@pytest.mark.unit
@pytest.mark.parametrize(("limit", "n"), [(1, 1), (3, 3), (5000, 10)])
def test_a_limit_in_range_returns_that_many_bars(client, bars, limit, n):
    r = client.get("/api/candles/NIFTY", params={"limit": limit})
    assert r.status_code == 200 and len(r.json()["bars"]) == n


@pytest.mark.unit
def test_the_default_still_works(client, bars):
    assert len(client.get("/api/candles/NIFTY").json()["bars"]) == 10
