"""Phase 3 of the quant plan: ATM implied volatility from end-of-day option closes."""

import math
from datetime import date, timedelta

import pandas as pd
import pytest

from tradingagents.analytics import implied_vol as iv
from tradingagents.integrations.optopsy.adapter import bs_price

R = 0.065


def chain_for(day, symbol, forward, expiries_vols, strikes, contracts=100):
    """Black-76 closes for calls and puts at known vols (one vol per expiry)."""
    rows = []
    for days, vol in expiries_vols:
        t = days / 365
        spot = forward * math.exp(-R * t)
        for k in strikes:
            for typ in ("CE", "PE"):
                rows.append({"trade_date": day, "symbol": symbol, "expiry": day + timedelta(days=days),
                             "strike": float(k), "option_type": typ, "contracts": contracts,
                             "close": bs_price(spot, k, t, R, vol, typ == "CE")})
    return pd.DataFrame(rows)


@pytest.mark.unit
def test_forward_and_atm_iv_are_recovered_from_closes():
    day = date(2026, 10, 16)
    chain = chain_for(day, "X", 1012.0, [(11, 0.25)], range(900, 1130, 20))
    atm = iv.expiry_atm(chain, R)
    assert atm["forward"] == pytest.approx(1012.0, rel=1e-4)
    assert atm["atm_strike"] == 1020.0
    assert atm["atm_iv"] == pytest.approx(0.25, abs=1e-3)


@pytest.mark.unit
def test_constant_maturity_interpolates_total_variance():
    pts = pd.DataFrame({"days": [10, 40], "atm_iv": [0.20, 0.30]})
    w = (40 - 30) / 30
    expected = math.sqrt((w * 0.04 * 10 + (1 - w) * 0.09 * 40) / 30)
    assert iv.constant_maturity(pts) == pytest.approx(expected)
    assert iv.constant_maturity(pd.DataFrame({"days": [45], "atm_iv": [0.3]})) == 0.3


@pytest.mark.unit
def test_table_skips_untraded_and_expiry_day_contracts():
    day = date(2026, 10, 16)
    good = chain_for(day, "X", 1000.0, [(11, 0.20), (39, 0.30)], range(900, 1110, 20))
    expiring = chain_for(day, "X", 1000.0, [(1, 0.90)], range(900, 1110, 20))
    stale = chain_for(day, "Y", 500.0, [(11, 0.40)], range(450, 560, 10), contracts=0)
    table = iv.atm_iv_table(pd.concat([good, expiring, stale]), R)
    assert list(table["symbol"]) == ["X"]
    row = table.iloc[0]
    assert row["near_days"] == 11 and row["near_iv"] == pytest.approx(0.20, abs=1e-3)
    assert 0.20 < row["iv30"] < 0.30
    assert row["expiries_used"] == 2
