"""Step 5, one bet: trades on the same view of the same index count as one bet.

A bet is source + symbol + direction (bullish / bearish / neutral); the expiry is not part of it. A trade joins a bet
when, at its taken_at, a trade of that bet was open (overnight too), or it is on the same day as one; chains count.
Won / lost is decided per bet by the sum of its trades' net; open bets are shown apart ("N bets open"). Net is closed
trades only; the open trades' P&L is its own line. Not-taken rows and rows entered outside the session are in no bet."""

import pytest

from webapp import strategist as st, trade_record as tr


# ---------------------------------------------------------------- one direction function

@pytest.mark.unit
@pytest.mark.parametrize("strategy", [s for s in st.STRATEGIES if s != "no_trade"])
def test_every_strategy_in_the_app_has_one_direction(strategy):
    assert tr.direction_of(strategy) in ("bullish", "bearish", "neutral")


@pytest.mark.unit
def test_the_directions_are_the_ones_the_strategies_bet_on():
    assert {s: tr.direction_of(s) for s in st.STRATEGIES if s != "no_trade"} == {
        "long_call": "bullish", "bull_call_spread": "bullish", "bull_put_spread": "bullish",
        "long_put": "bearish", "bear_put_spread": "bearish", "bear_call_spread": "bearish", "iron_condor": "neutral"}


@pytest.mark.unit
@pytest.mark.parametrize("strategy", ["no_trade", "straddle", "", None])
def test_an_unknown_strategy_is_an_error_not_a_default(strategy):
    with pytest.raises(ValueError, match="no direction"):
        tr.direction_of(strategy)
