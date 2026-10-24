"""Phase 7: does a pretrained time-series model (Chronos-Bolt) forecast volatility
better than our validated GARCH?

    python scripts/quant_chronos.py                     # all symbols
    python scripts/quant_chronos.py --symbols NIFTY RELIANCE

Needs the GARCH forecasts from ``quant_vol_forecasts.py`` (same dates, same QLIKE)
and ``pip install "tradingagents[chronos]"``. The keep rule is fixed in
``tradingagents/analytics/chronos_vol.py`` before any result: lower pooled QLIKE
than GARCH at 10 sessions and better than GARCH on at least two thirds of symbols.
Forecasts are saved to <store>/chronos/<symbol>.parquet; the run goes in the trial log.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import (  # noqa: E402
    chronos_vol as cv,
    trial_log,
    volatility_model as vm,  # noqa: E402
)
from tradingagents.analytics.datastore import store_root, write_parquet  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import SYMBOLS  # noqa: E402

IDEA = "chronos_bolt_vol"
CANDIDATES = ("chronos", "chronos_cal")
KEEP_HORIZON = 10
KEEP_SHARE = 2 / 3


def _returns(symbol: str) -> pd.Series:
    p = load_prices([symbol])
    s = pd.Series(p["adj_close"].to_numpy(), index=pd.to_datetime(p["trade_date"])).sort_index()
    return vm.log_returns(s)


def _stored(symbol: str) -> dict[str, pd.DataFrame]:
    flat = pd.read_parquet(store_root() / "vol_forecasts" / f"{symbol}.parquet")
    flat.index = pd.to_datetime(flat.index)
    return {m: flat[[f"{m}_h{h}" for h in vm.HORIZONS]].set_axis([f"h{h}" for h in vm.HORIZONS], axis=1)
            for m in ("garch", "gjr", "hist", "ewma")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    args = parser.parse_args()

    started = time.monotonic()
    pipe = cv.load_pipeline()
    tables = []
    for symbol in args.symbols:
        r = _returns(symbol)
        realised = vm.realised_vol(r)
        raw = cv.chronos_forecasts(r, pipe)
        forecasts = _stored(symbol) | {"chronos": raw, "chronos_cal": cv.calibrate(raw, realised)}
        flat = pd.concat({m: forecasts[m] for m in CANDIDATES}, axis=1)
        flat.columns = [f"{m}_{h}" for m, h in flat.columns]
        write_parquet(flat, store_root() / "chronos" / f"{symbol}.parquet", index=True)
        # Every model on the same dates: those where the calibrated forecast exists.
        t = vm.compare(forecasts, realised, baseline="garch")
        t["symbol"] = symbol
        tables.append(t)
        print(f"  {symbol} done ({(time.monotonic() - started) / 60:.1f} min)", flush=True)

    table = pd.concat(tables, ignore_index=True)
    table.to_csv(store_root() / "chronos" / "comparison.csv", index=False)
    pooled = table.groupby(["horizon", "model"])["qlike"].mean().unstack("model").round(4)
    print("\nMean out-of-sample QLIKE across symbols (lower is better):")
    print(pooled.to_string())
    t = table[table.model != "garch"]
    wins = t.assign(win=t.vs_baseline_t < 0, sig=t.vs_baseline_t < -2).groupby(["horizon", "model"])
    summary = pd.DataFrame({"beats": wins["win"].sum(), "significantly": wins["sig"].sum(), "of": wins["win"].size(),
                            "worse_significantly": wins["vs_baseline_t"].apply(lambda s: int((s > 2).sum()))})
    print("\nSymbols where the model beats GARCH (significantly = t < -2):")
    print(summary.to_string())

    verdicts = {}
    for m in CANDIDATES:
        row = summary.loc[(KEEP_HORIZON, m)]
        better_pooled = pooled.loc[KEEP_HORIZON, m] < pooled.loc[KEEP_HORIZON, "garch"]
        share = row["beats"] / row["of"]
        verdicts[m] = "keep" if better_pooled and share >= KEEP_SHARE else "reject"
        print(f"\n{m} at {KEEP_HORIZON} sessions: pooled QLIKE {pooled.loc[KEEP_HORIZON, m]:.4f} vs GARCH "
              f"{pooled.loc[KEEP_HORIZON, 'garch']:.4f}; beats GARCH on {row['beats']}/{row['of']} symbols "
              f"-> {verdicts[m].upper()}")

    n = int(table[(table.model == "garch") & (table.horizon == KEEP_HORIZON)]["n"].sum())
    for m in CANDIDATES:
        trial_log.record(trial_log.Trial(
            idea=f"{IDEA}_{m}", params={"model": cv.MODEL_ID, "context": cv.CONTEXT},
            universe=f"{len(args.symbols)} symbols", n_trials=1, n_oos_trades=n, verdict=verdicts[m],
            notes=f"h10 pooled QLIKE {pooled.loc[KEEP_HORIZON, m]:.4f} vs GARCH "
                  f"{pooled.loc[KEEP_HORIZON, 'garch']:.4f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
