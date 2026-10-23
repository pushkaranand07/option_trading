"""Phase 3 of the quant plan: VRP signal timing and the condor walk-forward."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import vrp as vp
from tradingagents.integrations.optopsy.adapter import bs_price

R = 0.065


def rolling_market(n=420, vol=0.15, seed=0):
    """Random-walk index with a monthly expiry on each month's last business day."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2020-01-01", periods=n)
    path = 1000 * np.exp(np.cumsum(rng.normal(0, vol / math.sqrt(252), n)))
    expiries = sorted({d.date() for d in pd.bdate_range(days[0], days[-1] + pd.Timedelta(days=70), freq="BME")})
    rows = []
    for day, f in zip(days.date, path, strict=True):
        for e in expiries:
            dte = (e - day).days
            if dte < 0 or dte > 70:
                continue
            t = dte / 365
            for k in np.arange(round(f * 0.85, -1), f * 1.15, 10.0):
                for typ in ("CE", "PE"):
                    p = bs_price(f * math.exp(-R * t), k, t, R, vol, typ == "CE") if t > 0 else \
                        max(0.0, (f - k) if typ == "CE" else (k - f))
                    rows.append({"trade_date": day, "symbol": "NIFTY", "expiry": e, "strike": float(k),
                                 "option_type": typ, "close": max(round(p, 2), 0.05),
                                 "settle": max(round(p, 2), 0.05), "contracts": 100})
    idx = pd.to_datetime(pd.Index(days.date))
    return pd.DataFrame(rows), pd.Series(path, index=idx), pd.Series(50, index=idx), idx


@pytest.mark.unit
def test_signal_on_session_t_uses_the_z_score_known_at_t_minus_1():
    idx = pd.bdate_range("2026-01-01", periods=400)
    vrp = pd.Series(0.0, index=idx)
    vrp.iloc[:-1] = np.random.default_rng(0).normal(0, 0.01, len(idx) - 1)
    vrp.iloc[300] = 0.10                       # a spike after the close of session 300
    sig = vp.vrp_signal(vrp, 2.0, idx)
    assert not sig.iloc[300] and sig.iloc[301]
    assert vp._signal_lookahead(vrp, idx, 2.0) == 0


@pytest.mark.unit
def test_vrp_is_iv_minus_forecast_on_common_dates():
    idx = pd.bdate_range("2026-01-01", periods=3)
    v = vp.vrp_series(pd.Series([0.20, 0.25, 0.30], index=idx), pd.Series([0.15, np.nan, 0.20], index=idx))
    assert list(v.round(4)) == [0.05, 0.10]


@pytest.mark.unit
def test_condor_walk_forward_runs_end_to_end_and_reports_baselines():
    chain, spot, lots, idx = rolling_market()
    vrp = pd.Series(np.random.default_rng(1).normal(0.02, 0.01, len(idx)), index=idx)
    result = vp.evaluate_condor("vrp-smoke", chain, spot, lots, vrp,
                                [{"z": 0.0}, {"z": 1.0}], train=150, test=60, embargo=45, random_runs=5)
    assert result.folds and len(result.oos_daily) >= 60
    assert "enter_whenever_possible" in result.baselines and "random_days_median" in result.baselines
    assert result.gates.verdict in {"rejected", "incomplete"}   # regimes are not evaluated before Phase 4
    assert "== vrp-smoke ==" in result.summary()


@pytest.mark.unit
def test_trades_are_tagged_with_the_regime_known_on_their_entry_day():
    from tradingagents.analytics.condor import CondorTrade

    def trade(day, pnl):
        return CondorTrade(day, day, {}, {}, 1, credit=10.0, max_risk=100.0, pnl=pnl)

    regimes = pd.Series(["calm", "stress"], index=pd.to_datetime(["2026-01-01", "2026-01-10"]))
    got = vp.regime_expectancy([trade(date(2026, 1, 5), 20.0), trade(date(2026, 1, 6), 40.0),
                                trade(date(2026, 1, 12), -50.0)], regimes)
    assert got == {"calm": pytest.approx(0.30), "stress": pytest.approx(-0.50)}
