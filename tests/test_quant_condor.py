"""Phase 3 of the quant plan: the end-of-day iron condor simulator."""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import condor as cd
from tradingagents.analytics.costs import ChargeRates, Slippage
from tradingagents.integrations.optopsy.adapter import bs_price

R = cd.DEFAULT_RISK_FREE
NO_COST = ChargeRates(stt=dict.fromkeys(("delivery", "intraday", "futures", "options"), (0.0, 0.0)),
                      stt_options_exercise=0.0,
                      exchange=dict.fromkeys(("delivery", "intraday", "futures", "options"), 0.0),
                      sebi_fee=0.0, stamp=dict.fromkeys(("delivery", "intraday", "futures", "options"), 0.0),
                      brokerage_flat=dict.fromkeys(("delivery", "intraday", "futures", "options"), 0.0))
NO_SLIP = Slippage(option_ticks=0, option_premium_pct=0.0)


def market(path, vol=0.15, start=date(2026, 1, 15), expiry=date(2026, 2, 24), strikes=range(800, 1210, 10)):
    """A chain priced by Black-76 at a flat vol along a given forward path (one monthly expiry)."""
    rows, spot = [], {}
    days = pd.bdate_range(start, periods=len(path)).date
    for day, f in zip(days, path, strict=True):
        spot[day] = f
        t = max((expiry - day).days, 0) / 365
        for k in strikes:
            for typ in ("CE", "PE"):
                if t > 0:
                    p = bs_price(f * math.exp(-R * t), k, t, R, vol, typ == "CE")
                else:
                    p = max(0.0, (f - k) if typ == "CE" else (k - f))
                rows.append({"trade_date": day, "symbol": "NIFTY", "expiry": expiry, "strike": float(k),
                             "option_type": typ, "close": round(max(p, 0.05), 2), "settle": round(max(p, 0.05), 2),
                             "contracts": 100})
    chain = pd.DataFrame(rows)
    idx = pd.to_datetime(pd.Index(days))
    return chain, pd.Series(spot).rename(index=pd.Timestamp), pd.Series(75, index=idx), idx


def enter_first_day(idx):
    s = pd.Series(False, index=idx)
    s.iloc[0] = True
    return s


@pytest.mark.unit
def test_strikes_are_chosen_by_delta_and_wings_by_width():
    chain, spot, lots, idx = market([1000.0] * 3)
    day = chain[chain["trade_date"] == chain["trade_date"].min()]
    strikes, prices, flags = cd.choose_strikes(day, cd.CondorParams(short_delta=0.20, wing_pct=0.03))
    assert strikes["long_put"] < strikes["short_put"] < 1000 < strikes["short_call"] < strikes["long_call"]
    assert strikes["short_put"] - strikes["long_put"] >= 30 and strikes["long_call"] - strikes["short_call"] >= 30
    assert flags == []


@pytest.mark.unit
def test_quiet_market_takes_profit_and_crash_stops_out():
    quiet, spot, lots, idx = market([1000.0] * 29)
    trades, daily = cd.simulate(quiet, spot, lots, enter_first_day(idx), rates=NO_COST, slippage=NO_SLIP)
    assert len(trades) == 1 and trades[0].exit_reason == "take_profit"
    assert trades[0].pnl > 0
    # The daily series adds up to the trade's return on risk.
    assert daily.sum() == pytest.approx(trades[0].return_on_risk, rel=1e-6)

    crash = [1000.0] * 3 + list(np.linspace(1000, 850, 10)) + [850.0] * 16
    chain, spot, lots, idx = market(crash)
    trades, daily = cd.simulate(chain, spot, lots, enter_first_day(idx), rates=NO_COST, slippage=NO_SLIP)
    assert trades[0].exit_reason == "stop_loss" and trades[0].pnl < 0
    # The stop is seen at one close and filled at the next.
    assert daily.sum() == pytest.approx(trades[0].return_on_risk, rel=1e-6)
    assert trades[0].return_on_risk >= -1.0 - 1e-9          # never worse than the defined max risk


@pytest.mark.unit
def test_held_to_expiry_settles_at_intrinsic_against_the_index():
    path = [1000.0] * 29                     # Jan 15 .. Feb 24: ends on the expiry date
    chain, spot, lots, idx = market(path)
    params = cd.CondorParams(take_profit=10.0, stop_loss=10.0)   # never triggers
    trades, _ = cd.simulate(chain, spot, lots, enter_first_day(idx), params, NO_COST, NO_SLIP)
    t = trades[0]
    assert t.exit_reason == "expiry" and t.exit_date == date(2026, 2, 24)
    assert all(v == 0 for v in t.exit_prices.values())          # all legs expire worthless at 1000
    assert t.pnl == pytest.approx(t.credit * t.lot)


@pytest.mark.unit
def test_costs_and_slippage_reduce_the_result():
    chain, spot, lots, idx = market([1000.0] * 29)
    free, _ = cd.simulate(chain, spot, lots, enter_first_day(idx), rates=NO_COST, slippage=NO_SLIP)
    real, _ = cd.simulate(chain, spot, lots, enter_first_day(idx))
    assert real[0].pnl < free[0].pnl
    assert real[0].charges > 8 * 20      # eight orders at Rs 20 brokerage, plus statutory charges


@pytest.mark.unit
def test_only_monthly_expiries_are_traded_and_signal_off_means_no_trade():
    chain, spot, lots, idx = market([1000.0] * 5)
    weekly = chain.assign(expiry=date(2026, 2, 10))
    both = pd.concat([chain, weekly])
    assert cd.monthly_expiries(both) == {date(2026, 2, 24)}
    trades, daily = cd.simulate(chain, spot, lots, pd.Series(False, index=idx))
    assert trades == [] and (daily == 0).all()


@pytest.mark.unit
def test_each_trades_daily_share_sums_to_its_return_and_a_missing_expiry_close_still_settles():
    chain, spot, lots, idx = market([1000.0] * 29)
    params = cd.CondorParams(take_profit=10.0, stop_loss=10.0)
    no_expiry_close = spot.drop(spot.index[-1])                   # expiry-day index close missing
    trades, daily = cd.simulate(chain, no_expiry_close, lots, enter_first_day(idx), params, NO_COST, NO_SLIP)
    t = trades[0]
    assert sum(t.daily.values()) == pytest.approx(t.return_on_risk)
    assert sum(t.daily.values()) == pytest.approx(daily.sum())
    assert any("last earlier close" in f for f in t.flags)
    assert t.pnl == pytest.approx(t.credit * t.lot)               # all legs expire worthless at 1000
