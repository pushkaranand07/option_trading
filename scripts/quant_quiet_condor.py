"""Approach A, step 2: iron condors on the 5 stocks GARCH predicts quietest.

    python scripts/quant_quiet_condor.py
    python scripts/quant_quiet_condor.py --random-runs 50

Every 10 sessions, rank the 29 stocks by GARCH 10-session forecast / trailing vol
and open a monthly iron condor (delta 0.20, 4% wings, 50% / 2x exits) on the 5
lowest. Compared with the same condors on 5 random stocks and on all stocks.
Settles on NSE's futures close; lot sizes from the store. One trial.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds, quiet_condor as qc, trial_log  # noqa: E402
from tradingagents.analytics.ml.inputs import garch_move_score  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS, SURVIVORSHIP_NOTE  # noqa: E402

IDEA = "quiet_stock_condor_garch"


def load_symbol(symbol: str):
    chain = ds.load("option_chain", symbols=[symbol])
    fo = ds.load("fo_summary", symbols=[symbol])
    fo["trade_date"] = pd.to_datetime(fo["trade_date"])
    fo = fo.set_index("trade_date")
    # The near-month future converges to the stock on expiry: settle on it (real rupees,
    # the same basis as the strikes), never on Yahoo's split-adjusted close.
    return chain, fo["fut_close"], fo["lot_size"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--random-runs", type=int, default=100)
    args = parser.parse_args()

    prices = load_prices(STOCKS)
    closes = (prices.assign(trade_date=pd.to_datetime(prices["trade_date"]))
              .pivot(index="trade_date", columns="symbol", values="adj_close").sort_index())
    score = garch_move_score(closes)
    start = score.dropna(how="all").index[0]
    print(f"GARCH scores from {start:%Y-%m-%d}; {score.shape[1]} stocks", flush=True)
    regimes = None
    f = ds.store_root() / "regime" / "regime.parquet"
    if f.exists():
        r = pd.read_parquet(f)
        regimes = pd.Series(r["regime"].to_numpy(), index=pd.to_datetime(r["trade_date"])).shift(1).dropna()

    def progress(i, n, symbol):
        print(f"  {i}/{n} {symbol}", flush=True)

    result = qc.run(score, load_symbol, start, random_runs=args.random_runs, regimes=regimes, progress=progress)
    print(result.summary())
    print(f"\n{SURVIVORSHIP_NOTE}")
    r = result.picks_daily
    trial_log.record(trial_log.Trial(
        idea=IDEA, params={"k": 5, "horizon": 10, "short_delta": 0.20, "wing_pct": 0.04},
        universe="29 F&O stocks since 2018", data_start=str(r.index[0].date()), data_end=str(r.index[-1].date()),
        n_trials=1, n_oos_trades=len(result.trades), oos_sharpe=result.sharpe, dsr=result.deflated_sharpe,
        verdict=result.verdict, gate_verdict=result.gates.verdict,
        notes=f"beats random {result.random_percentile:.0%}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
