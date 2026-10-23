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
from tradingagents.analytics.implied_vol import atm_iv_table  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.vrp import evaluate_condor, vrp_series  # noqa: E402

GRID = [{"short_delta": d, "wing_pct": w, "z": z}
        for d in (0.15, 0.20, 0.25) for w in (0.02, 0.04) for z in (0.5, 1.0, 1.5)]


def inputs(symbol: str):
    chain = ds.load("option_chain", symbols=[symbol])
    summary = ds.load("fo_summary", symbols=[symbol])
    summary["trade_date"] = pd.to_datetime(summary["trade_date"])
    lots = summary.set_index("trade_date")["lot_size"]
    # Expiry settlement: the index close (Yahoo); where Yahoo lacks a day, the
    # expiring future's close, which converges to the index on expiry.
    yahoo = load_prices([symbol])
    spot = pd.Series(yahoo["close"].to_numpy(), index=pd.to_datetime(yahoo["trade_date"]))
    spot = spot.combine_first(summary.set_index("trade_date")["fut_close"])
    iv = atm_iv_table(chain)
    iv30 = pd.Series(iv["iv30"].to_numpy(), index=pd.to_datetime(iv["trade_date"]))
    garch = pd.read_parquet(ds.store_root() / "vol_forecasts" / f"{symbol}.parquet")["garch_h21"]
    garch.index = pd.to_datetime(garch.index)
    return chain, spot, lots, vrp_series(iv30, garch)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=["NIFTY", "BANKNIFTY"])
    parser.add_argument("--random-runs", type=int, default=100)
    args = parser.parse_args()
    regimes = None
    regime_file = ds.store_root() / "regime" / "regime.parquet"
    if regime_file.exists():
        r = pd.read_parquet(regime_file)
        # The label known at the start of session t is the one dated t-1.
        regimes = pd.Series(r["regime"].to_numpy(), index=pd.to_datetime(r["trade_date"])).shift(1).dropna()
    else:
        print("No regimes yet (run scripts/quant_regime.py): the regime gate will read not_evaluated.")
    for symbol in args.symbols:
        chain, spot, lots, vrp = inputs(symbol)
        print(f"{symbol}: {chain['trade_date'].nunique()} sessions of options, VRP on {len(vrp)} days, "
              f"mean VRP {vrp.mean():+.3f}", flush=True)
        result = evaluate_condor(f"vrp_condor_{symbol}", chain, spot, lots, vrp, GRID,
                                 random_runs=args.random_runs, regimes=regimes)
        print(result.summary(), "\n", flush=True)
        r = result.oos_daily
        trial_log.record(trial_log.Trial(
            idea=result.name, params={"grid": GRID}, universe=symbol, data_start=str(r.index[0].date()),
            data_end=str(r.index[-1].date()), n_trials=len(GRID), n_oos_trades=len(result.oos_trades),
            is_sharpe=result.in_sample_sharpe, oos_sharpe=result.oos_sharpe, dsr=result.deflated_sharpe,
            verdict=result.verdict, gate_verdict=result.gates.verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
