"""Regression tests for three option_backtester / adapter bugs found in review (2026-10-23).

1. Early exits could trigger after the planned ``exit_dte`` exit.
2. Commission was never deducted from the simulator's realized P&L.
3. Expiry-day values used the option's last close, and untraded expiry-day
   contracts were dropped, instead of NSE settlement at intrinsic value.
"""

from datetime import date, timedelta

import pandas as pd
import pytest

import option_backtester as op
from tradingagents.integrations.optopsy.adapter import bhavcopy_to_optopsy

EXPIRY = pd.Timestamp("2026-03-31")


def one_call_chain(prices_by_dte: dict[int, float], strike: float = 100.0) -> pd.DataFrame:
    """A single call quoted on the given days-to-expiry, at the given prices."""
    rows = [{"underlying_symbol": "X", "underlying_price": 100.0, "option_type": "call",
             "expiration": EXPIRY, "quote_date": EXPIRY - pd.Timedelta(days=dte), "strike": strike,
             "bid": p, "ask": p, "delta": 0.30}
            for dte, p in sorted(prices_by_dte.items(), reverse=True)]
    df = pd.DataFrame(rows)
    for col in ("expiration", "quote_date"):
        df[col] = df[col].astype("datetime64[us]")
    return df


@pytest.mark.unit
def test_a_take_profit_after_the_planned_exit_does_not_count():
    # Flat at 10 until the planned exit at 5 days left, then jumps to 30 at 3 days left.
    chain = one_call_chain({20: 10.0, 15: 10.0, 10: 10.0, 5: 10.0, 3: 30.0, 0: 30.0})
    out = op.long_calls(chain, max_entry_dte=20, exit_dte=5, take_profit=0.5, raw=True)
    first = out[out["dte_entry"] == 20]
    assert len(first) == 1
    assert first["exit_type"].iloc[0] != "take_profit"


@pytest.mark.unit
def test_a_take_profit_before_the_planned_exit_still_counts():
    chain = one_call_chain({20: 10.0, 15: 10.0, 10: 30.0, 5: 30.0, 0: 30.0})
    out = op.long_calls(chain, max_entry_dte=20, exit_dte=5, take_profit=0.5, raw=True)
    assert out.loc[out["dte_entry"] == 20, "exit_type"].iloc[0] == "take_profit"


@pytest.mark.unit
def test_commission_is_deducted_from_realized_pnl():
    chain = one_call_chain({20: 10.0, 0: 12.0})
    free = op.simulate(chain, op.long_calls, max_entry_dte=20, exit_dte=0, quantity=2, multiplier=75)
    fee = {"per_contract": 20.0, "base_fee": 0.0, "min_fee": 0.0, "per_share": 0.0}
    paid = op.simulate(chain, op.long_calls, max_entry_dte=20, exit_dte=0, quantity=2, multiplier=75,
                       commission=fee)
    gross = free.trade_log["realized_pnl"].iloc[0]
    assert gross == pytest.approx((12.0 - 10.0) * 2 * 75)
    # Rs 20 per contract, entry and exit, for 2 contract sets.
    assert paid.trade_log["realized_pnl"].iloc[0] == pytest.approx(gross - 20.0 * 2 * 2)
    assert paid.trade_log["pct_change"].iloc[0] == pytest.approx((gross - 80.0) / (10.0 * 2 * 75))


@pytest.mark.unit
def test_expiry_day_contracts_settle_at_intrinsic_even_when_untraded():
    day = date(2026, 9, 22)
    rows = [
        {"trade_date": day, "symbol": "NIFTY", "expiry": day, "strike": 23000.0, "option_type": "CE",
         "close": 255.0, "underlying_price": 23300.0, "contracts": 500, "open_interest": 1},     # ITM
        {"trade_date": day, "symbol": "NIFTY", "expiry": day, "strike": 22500.0, "option_type": "PE",
         "close": 3.5, "underlying_price": 23300.0, "contracts": 0, "open_interest": 1},          # untraded wing
        {"trade_date": day - timedelta(days=7), "symbol": "NIFTY", "expiry": day, "strike": 25000.0,
         "option_type": "CE", "close": 1.0, "underlying_price": 23000.0, "contracts": 0, "open_interest": 1},
    ]
    chain = bhavcopy_to_optopsy(pd.DataFrame(rows), "NIFTY").set_index(["option_type", "strike"])
    assert chain.loc[("call", 23000.0), "bid"] == pytest.approx(300.0)     # intrinsic, not the 255 close
    assert chain.loc[("put", 22500.0), "bid"] == 0.0                     # kept, and worthless
    assert ("call", 25000.0) not in chain.index                          # untraded before expiry: dropped
    assert any("valued at intrinsic" in a for a in chain.attrs["approximations"])
