"""Approach A, step 2: condors on the stocks predicted quietest."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import quiet_condor as qc

sys.path.insert(0, str(Path(__file__).parent))
from test_quant_vrp import rolling_market  # noqa: E402


@pytest.mark.unit
def test_picks_are_the_lowest_scores_on_each_rebalance_date():
    idx = pd.bdate_range("2026-01-01", periods=25)
    score = pd.DataFrame({"A": 1.0, "B": 0.5, "C": 2.0, "D": np.nan}, index=idx)
    dates = qc.rebalance_dates(score, idx[0], horizon=10)
    assert list(dates) == [idx[0], idx[10], idx[20]]
    assert qc.selections(score, dates, k=2)[idx[0]] == ["B", "A"]         # D has no score: skipped
    rand = qc.random_selections(score, dates, k=2, runs=3)
    assert all(len(r[d]) == 2 and "D" not in r[d] for r in rand for d in dates)


@pytest.mark.unit
def test_run_combines_stocks_and_baselines():
    markets = {s: rolling_market(n=300, seed=i) for i, s in enumerate(["A", "B", "C"])}
    idx = markets["A"][3]
    score = pd.DataFrame(np.random.default_rng(0).random((len(idx), 3)), index=idx, columns=list("ABC"))

    def load(symbol):
        chain, spot, lots, _ = markets[symbol]
        return chain.assign(symbol=symbol), spot, lots

    result = qc.run(score, load, idx[0], k=2, horizon=10, random_runs=5)
    assert len(result.trades) > 0 and len(result.random_sharpes) == 5
    assert set(result.neighbour_sharpes) == {0.15, 0.25}
    assert "Quiet-stock condors" in result.summary()
