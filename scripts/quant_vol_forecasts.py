"""Phase 3 exit check, part 1: do GARCH forecasts beat simple volatility estimates?

    python scripts/quant_vol_forecasts.py                 # all symbols, 8 processes
    python scripts/quant_vol_forecasts.py --symbols NIFTY RELIANCE --workers 2

Forecasts are saved to <store>/vol_forecasts/<symbol>.parquet. The report pools
the out-of-sample QLIKE over symbols and counts, per model, the symbols where
it beats each baseline. For NIFTY, India VIX (the market's own 30-day
forecast) is scored against the 21-session horizon too.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import volatility_model as vm  # noqa: E402
from tradingagents.analytics.datastore import store_root  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import SYMBOLS  # noqa: E402

MODELS = ("garch", "gjr", "egarch")


def _returns(symbol: str) -> pd.Series:
    p = load_prices([symbol])
    s = pd.Series(p["adj_close"].to_numpy(), index=pd.to_datetime(p["trade_date"])).sort_index()
    return vm.log_returns(s)


def run_symbol(symbol: str) -> tuple[str, pd.DataFrame]:
    r = _returns(symbol)
    forecasts = {m: vm.garch_forecasts(r, m) for m in MODELS}
    forecasts["hist"] = vm.hist_vol_forecasts(r)
    forecasts["ewma"] = vm.ewma_forecasts(r)
    wide = pd.concat(forecasts, axis=1)
    wide.columns.names = ["model", "horizon"]
    path = store_root() / "vol_forecasts" / f"{symbol}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    flat = wide.copy()
    flat.columns = [f"{m}_{h}" for m, h in flat.columns]
    flat.to_parquet(path)
    return symbol, wide


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=list(SYMBOLS))
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    started = time.monotonic()
    results = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_symbol, s) for s in args.symbols]
        for fut in as_completed(futures):
            symbol, wide = fut.result()
            results[symbol] = wide
            print(f"  {symbol} done ({(time.monotonic() - started) / 60:.1f} min)", flush=True)

    tables = []
    for symbol, wide in results.items():
        realised = vm.realised_vol(_returns(symbol))
        forecasts = {m: wide[m] for m in wide.columns.get_level_values(0).unique()}
        for baseline in ("hist", "ewma"):
            t = vm.compare(forecasts, realised, baseline=baseline)
            t["symbol"], t["baseline"] = symbol, baseline
            tables.append(t)
    table = pd.concat(tables, ignore_index=True)
    table.to_csv(store_root() / "vol_forecasts" / "comparison.csv", index=False)

    pooled = (table[table.baseline == "hist"].groupby(["horizon", "model"])["qlike"].mean()
              .unstack("model").round(4))
    print("\nMean out-of-sample QLIKE across symbols (lower is better):")
    print(pooled.to_string())
    for baseline in ("hist", "ewma"):
        t = table[(table.baseline == baseline) & (table.model != baseline)]
        wins = t.assign(win=t.vs_baseline_t < 0, sig=t.vs_baseline_t < -2).groupby(["horizon", "model"])
        summary = pd.DataFrame({"beats": wins["win"].sum(), "significantly": wins["sig"].sum(),
                                "of": wins["win"].size()})
        print(f"\nSymbols where the model beats '{baseline}' (significantly = t < -2):")
        print(summary.to_string())

    if "NIFTY" in results:
        vix = load_prices(["INDIAVIX"])
        vix = pd.Series(vix["close"].to_numpy() / 100.0, index=pd.to_datetime(vix["trade_date"])).sort_index()
        nifty = results["NIFTY"]
        forecasts = {m: nifty[m][["h21"]] for m in MODELS + ("hist", "ewma")}
        forecasts["india_vix"] = vix.to_frame("h21")
        t = vm.compare(forecasts, vm.realised_vol(_returns("NIFTY"))[["h21"]], baseline="india_vix")
        print("\nNIFTY 21-session horizon vs India VIX (negative t = better than VIX):")
        print(t[["model", "qlike", "n", "vs_baseline_t"]].round(4).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
