"""Backward holdout for the frozen pooled VRP condor, and the combined Stage 1 evidence.

    python scripts/quant_holdout.py

1. Holdout: the frozen rules (paper_strategies.VRP_POOLED_PARAMS), unchanged, on
   entries before 2021-04-05 — years the settings' selection never saw. Built in
   memory from raw NSE files (2015-2017), the store (2018+) and Yahoo prices for
   GARCH training; the production store and the paper ledger are not touched.
2. Combined: holdout trades + the frozen rules' trades from 2021 on (production
   inputs), judged on trade count, mean and bootstrap interval.
Needs 2015-2017 F&O and index files: scripts/quant_backfill.py --start 2015-01-01
--end 2017-12-31 --kinds fo indices.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import holdout as ho, stress as st, trial_log  # noqa: E402
from tradingagents.analytics.paper_strategies import VRP_POOLED_PARAMS  # noqa: E402

HOLDOUT_END = date(2021, 4, 4)      # the walk-forward's out-of-sample period starts 2021-04-05


def main() -> int:
    print("Building 2015+ inputs in memory (raw NSE files + store + Yahoo for GARCH)...", flush=True)
    inputs = {s: ho.build_inputs(s) for s in VRP_POOLED_PARAMS}
    for s, (chain, _, lots, vrp) in inputs.items():
        print(f"  {s}: options from {chain['trade_date'].min()}, VRP from {vrp.index.min():%Y-%m-%d}, "
              f"lots {sorted(lots.dropna().astype(int).unique())[:6]}", flush=True)
    result = ho.run(inputs, VRP_POOLED_PARAMS, end=HOLDOUT_END)
    print()
    print(result.summary())

    # Combined evidence: holdout + the frozen rules' later trades (production inputs, as in Stage 2).
    import quant_stress as qs  # noqa: E402  (same directory)

    from tradingagents.analytics import vrp as vp  # noqa: E402

    later = qs.run({s: vp.load_inputs(s) for s in VRP_POOLED_PARAMS})
    later = [t for t in later if t.entry_date > HOLDOUT_END]
    allr = np.array([t.return_on_risk for t in result.trades] + [t.return_on_risk for t in later])
    lo, hi = st.block_bootstrap_ci(allr)
    print(f"\nCombined frozen-rules record: {len(result.trades)} holdout + {len(later)} later = {len(allr)} trades | "
          f"mean {allr.mean():+.2%} | wins {(allr > 0).mean():.0%} | bootstrap 95% [{lo:+.2%}, {hi:+.2%}]")
    holdout_ok = len(result.trades) > 0 and result.ci[0] > 0 and result.random_percentile >= 0.95
    combined_ok = len(allr) >= 100 and lo > 0
    print(f"Holdout verdict: {'PASS' if holdout_ok else 'FAIL'} (mean CI above 0 and beats random >= 95%)")
    print(f"Combined trade-count gate (>= 100) and CI: {'PASS' if combined_ok else 'FAIL'}")
    r = np.array([t.return_on_risk for t in result.trades])
    trial_log.record(trial_log.Trial(
        idea="vrp_condor_pooled_holdout", params=VRP_POOLED_PARAMS, universe="NIFTY+BANKNIFTY",
        data_start=str(result.first_entry), data_end=str(HOLDOUT_END), n_trials=1, n_oos_trades=len(r),
        oos_sharpe=None, dsr=None, verdict="holdout_pass" if holdout_ok else "holdout_fail", gate_verdict=None,
        notes=f"mean {r.mean() if len(r) else float('nan'):+.4f}; CI {result.ci}; beats random "
              f"{result.random_percentile}; combined {len(allr)} trades CI [{lo:+.4f}, {hi:+.4f}]"))
    return 0 if holdout_ok and combined_ok else 1


if __name__ == "__main__":
    sys.exit(main())
