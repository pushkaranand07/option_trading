"""Stage 2 of the proof plan: stress-test arithmetic."""

import numpy as np
import pytest

from tradingagents.analytics import stress as st
from tradingagents.analytics.costs import DEFAULT_RATES, DEFAULT_SLIPPAGE, OPTIONS, fill_charges


@pytest.mark.unit
def test_doubled_rates_double_every_charge():
    single = fill_charges(OPTIONS, 75, 100, "sell")
    double = fill_charges(OPTIONS, 75, 100, "sell", st.scaled_rates(DEFAULT_RATES, 2.0))
    assert double == pytest.approx(2 * single)
    slip = st.scaled_slippage(DEFAULT_SLIPPAGE, 3.0)
    assert slip.option_ticks == 3 and slip.option_premium_pct == pytest.approx(0.03)


@pytest.mark.unit
def test_bootstrap_interval_brackets_the_mean_and_excludes_zero_for_a_clear_edge():
    r = np.random.default_rng(0).normal(0.10, 0.20, 100)
    lo, hi = st.block_bootstrap_ci(r)
    assert lo < r.mean() < hi and lo > 0
    lo, hi = st.block_bootstrap_ci(np.random.default_rng(1).normal(0.0, 0.20, 100))
    assert lo < 0 < hi


@pytest.mark.unit
def test_drawdown_in_risk_units():
    assert st.max_drawdown_units([0.2, -0.5, -0.3, 0.4]) == pytest.approx(-0.8)
    assert st.max_drawdown_units([0.1, 0.1]) == 0.0
    worst = st.drawdown_monte_carlo([0.2] * 20 + [-1.0] * 3, runs=2000)
    assert -3.0 <= worst <= -1.0
