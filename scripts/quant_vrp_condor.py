"""Phase 3 exit check, part 2: does the VRP signal make monthly iron condors pay?

    python scripts/quant_vrp_condor.py                      # NIFTY and BANKNIFTY
    python scripts/quant_vrp_condor.py --symbols NIFTY --random-runs 50

Needs the built store (scripts/quant_build_store.py) and GARCH forecasts
(scripts/quant_vol_forecasts.py). Grid: short delta x wing width x VRP z,
18 combinations, all logged to the trial log.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import (
    datastore as ds,  # noqa: E402
    trial_log,  # noqa: E402
)
from tradingagents.analytics.vrp import evaluate_condor, load_inputs, pool  # noqa: E402

GRID = [{"short_delta": d, "wing_pct": w, "z": z}
        for d in (0.15, 0.20, 0.25) for w in (0.02, 0.04) for z in (0.5, 1.0, 1.5)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=["NIFTY", "BANKNIFTY"])
    parser.add_argument("--random-runs", type=int, default=100)
    parser.add_argument("--books", type=int, default=1,
                        help="staggered condor books (4 = a new monthly condor about every week)")
    parser.add_argument("--pool", action="store_true", help="also judge all symbols together, capital split")
    args = parser.parse_args()
    regimes = None
    regime_file = ds.store_root() / "regime" / "regime.parquet"
    if regime_file.exists():
        r = pd.read_parquet(regime_file)
        # The label known at the start of session t is the one dated t-1.
        regimes = pd.Series(r["regime"].to_numpy(), index=pd.to_datetime(r["trade_date"])).shift(1).dropna()
    else:
        print("No regimes yet (run scripts/quant_regime.py): the regime gate will read not_evaluated.")
    tag = f"_books{args.books}" if args.books > 1 else ""
    results = []
    for symbol in args.symbols:
        chain, spot, lots, vrp = load_inputs(symbol)
        print(f"{symbol}: {chain['trade_date'].nunique()} sessions of options, VRP on {len(vrp)} days, "
              f"mean VRP {vrp.mean():+.3f}", flush=True)
        result = evaluate_condor(f"vrp_condor_{symbol}{tag}", chain, spot, lots, vrp, GRID,
                                 random_runs=args.random_runs, regimes=regimes, books=args.books)
        print(result.summary(), "\n", flush=True)
        _record(result, symbol, len(GRID))
        results.append(result)
    if args.pool and len(results) > 1:
        pooled = pool(results, n_trials=len(GRID) * len(results), regimes=regimes)
        print(pooled.summary(), flush=True)
        _record(pooled, "+".join(args.symbols), len(GRID) * len(results))
    return 0


def _record(result, universe: str, n_trials: int) -> None:
    r = result.oos_daily
    trial_log.record(trial_log.Trial(
        idea=result.name, params={"grid": GRID}, universe=universe, data_start=str(r.index[0].date()),
        data_end=str(r.index[-1].date()), n_trials=n_trials, n_oos_trades=len(result.oos_trades),
        is_sharpe=result.in_sample_sharpe, oos_sharpe=result.oos_sharpe, dsr=result.deflated_sharpe,
        verdict=result.verdict, gate_verdict=result.gates.verdict))


if __name__ == "__main__":
    sys.exit(main())
