"""Phase 4: fit the market regime model on NIFTY and check it is worth having.

    python scripts/quant_regime.py

Saves <store>/regime/regime.parquet (probabilities, stable label, known_from)
and prints, out of sample:
- each regime's share of days and the returns / volatility that FOLLOWED it
  (a regime is useful only if what comes next differs by regime);
- how the Phase 2 baselines did by regime (the regime gate's input).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import regime as rg  # noqa: E402
from tradingagents.analytics.datastore import (  # noqa: E402
    add_known_from,
    next_sessions,
    store_root,
    write_parquet,
)
from tradingagents.analytics.evaluate import buy_and_hold, evaluate, moving_average_trend, panel  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402
from tradingagents.analytics.universe import STOCKS  # noqa: E402


def wide(prices: pd.DataFrame, column: str) -> pd.DataFrame:
    p = prices.assign(trade_date=pd.to_datetime(prices["trade_date"]))
    return p.pivot(index="trade_date", columns="symbol", values=column).sort_index()


def main() -> int:
    prices = load_prices()
    closes = wide(prices, "adj_close")
    feats = rg.features(closes["NIFTY"], wide(prices, "close")["INDIAVIX"], closes[list(STOCKS)])
    print(f"Features: {len(feats)} days, {feats.index[0]:%Y-%m-%d} to {feats.index[-1]:%Y-%m-%d}")

    probs = rg.regime_probabilities(feats)
    labels = rg.stable_labels(probs)
    out = probs.assign(regime=labels).reset_index(names="trade_date")
    out["trade_date"] = out["trade_date"].dt.date
    out = add_known_from(out, next_sessions(out["trade_date"]))
    path = write_parquet(out, store_root() / "regime" / "regime.parquet")
    print(f"Saved {len(out)} days of regimes -> {path}")
    print(f"Current regime ({labels.index[-1]:%Y-%m-%d}): {labels.iloc[-1]} "
          f"({probs.iloc[-1].round(2).to_dict()})")

    print("\nOut of sample: what followed each regime (NIFTY)")
    print(rg.describe(labels, closes["NIFTY"]).round(4).to_string())
    switches = int((labels != labels.shift()).sum() - 1)
    print(f"Label changes: {switches} in {len(labels)} days")

    # The label known at the start of session t is the one dated t-1.
    known = labels.shift(1).dropna()
    data = panel(prices[prices["symbol"].isin(STOCKS)])
    for name, signal, grid in (("buy_and_hold", buy_and_hold, [{}]),
                               ("ma_trend", moving_average_trend, [{"fast": 50, "slow": 200}])):
        result = evaluate(f"regime_check_{name}", signal, grid, data, position_value=100_000,
                          segment="delivery", regimes=known, random_runs=0, log=False)
        print(f"\n{name}: mean trade return by regime at entry: "
              + ", ".join(f"{k} {v:+.2%}" for k, v in result.by_regime.items()))
        port = result.portfolio_returns
        by_day = port.groupby(known.reindex(port.index)).agg(["mean", "std", "count"])
        by_day["annualised"] = by_day["mean"] * 252
        print(by_day.round(5).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
