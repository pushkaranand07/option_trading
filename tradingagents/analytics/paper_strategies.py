"""Strategies admitted to forward paper trading (PROOF_PLAN.md, Stage 3).

Each entry reproduces its frozen spec in docs/strategies/ exactly. Changing an
entry means a new strategy: give it a new name and start date, never edit one in
place (the ledger keys trades by strategy name).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date

import pandas as pd

from tradingagents.analytics import condor as cd, vrp as vp
from tradingagents.analytics.paper import PaperStrategy

# docs/strategies/vrp_condor_pooled.md — the walk-forward's most frequent choice per index.
VRP_POOLED_PARAMS = {
    "NIFTY": {"short_delta": 0.25, "wing_pct": 0.04, "z": 1.5},
    "BANKNIFTY": {"short_delta": 0.15, "wing_pct": 0.04, "z": 0.5},
}


def simulate_vrp_pooled() -> list:
    trades = []
    for symbol, p in VRP_POOLED_PARAMS.items():
        chain, spot, lots, vrp = vp.load_inputs(symbol)
        sessions = pd.to_datetime(pd.Index(sorted(set(pd.to_datetime(chain["trade_date"])))))
        signal = vp.vrp_signal(vrp, p["z"], sessions)
        params = replace(cd.CondorParams(), short_delta=p["short_delta"], wing_pct=p["wing_pct"])
        book, _ = cd.simulate_staggered(chain, spot, lots, signal, params, books=4, include_open=True)
        for t in book:
            t.symbol = symbol
        trades += book
    return trades


STRATEGIES = [
    PaperStrategy(
        name="vrp_condor_pooled",
        spec="docs/strategies/vrp_condor_pooled.md",
        # Frozen on Fri 2026-10-23 after the close: paper trades start with the next session.
        start=date(2026, 10, 26),
        simulate=simulate_vrp_pooled,
        # Expected range: the frozen rules' 2021-26 trades returned +11.1% of max risk on
        # average with a spread of 20% (95 trades). Those settings were picked on that
        # period, so the mean is optimistic; it is used as stated, and Stage 3 still
        # requires at least 30 forward trades.
        backtest_mean=0.111,
        backtest_sd=0.202,
        # Rejected 2026-10-23: the backward holdout (2015 to Mar-2021, years the settings never
        # saw) gave -5.6% of risk per trade over 95 trades, no better than random entry (60%).
        # Kept as observation only, at the user's choice.
        status="observation",
        note="backward holdout failed: -5.6% of risk/trade 2015-21, beats random 60%",
    ),
]
