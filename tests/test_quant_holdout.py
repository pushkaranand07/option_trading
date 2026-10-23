"""Stage 1 evidence: the backward holdout runner."""

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import holdout as ho

sys.path.insert(0, str(Path(__file__).parent))
from test_quant_vrp import rolling_market  # noqa: E402


@pytest.mark.unit
def test_holdout_keeps_only_entries_up_to_the_end_and_reports_baselines():
    inputs = {}
    for i, s in enumerate(["NIFTY", "BANKNIFTY"]):
        chain, spot, lots, idx = rolling_market(n=380, seed=i)
        vrp = pd.Series(np.random.default_rng(i).normal(0.02, 0.01, len(idx)), index=idx)
        inputs[s] = (chain.assign(symbol=s), spot, lots, vrp)
    params = {"NIFTY": {"short_delta": 0.25, "wing_pct": 0.04, "z": 0.0},
              "BANKNIFTY": {"short_delta": 0.15, "wing_pct": 0.04, "z": 0.0}}
    end = date(2021, 3, 31)
    result = ho.run(inputs, params, end=end, random_runs=5)
    assert result.trades and all(t.entry_date <= end for t in result.trades)
    assert set(result.symbol_trades) == {"NIFTY", "BANKNIFTY"}
    assert len(result.random_means) == 5 and np.isfinite(result.always_mean)
    assert "Backward holdout" in result.summary()
