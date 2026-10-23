"""Build the point-in-time Parquet store from downloaded raw files (plan, Phase 1).

    python scripts/quant_build_store.py                # every year, plus Yahoo prices
    python scripts/quant_build_store.py --years 2026   # rebuild one year
    python scripts/quant_build_store.py --skip-prices

Run scripts/quant_backfill.py first. Rebuilding is safe: each year's files are
replaced whole. Prints a data-quality summary at the end; the full list of
issues goes to <store>/quality_report.csv.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds  # noqa: E402
from tradingagents.analytics.backfill import load_manifest, raw_root  # noqa: E402
from tradingagents.analytics.implied_vol import atm_iv_table  # noqa: E402
from tradingagents.analytics.prices import (  # noqa: E402
    fetch_prices,
    fill_stock_gaps,
    merge_nse_indices,
    quality_report,
    save_prices,
)
from tradingagents.analytics.universe import SURVIVORSHIP_NOTE, SYMBOLS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int)
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--datasets", nargs="+", choices=ds.DATASETS, default=list(ds.DATASETS),
                        help="rebuild only these (e.g. index_close after downloading index files)")
    args = parser.parse_args()

    manifest = load_manifest(raw_root())
    trading_days = sorted(d for (d, k), r in manifest.items() if k == "fo" and r.status == "ok")
    if not trading_days:
        print("No raw files yet: run scripts/quant_backfill.py first.")
        return 1
    years = args.years or sorted({d.year for d in trading_days})
    print(f"{len(trading_days)} NSE trading days, {trading_days[0]} to {trading_days[-1]}")

    for year in years:
        started = time.monotonic()
        counts = ds.build_year(year, datasets=tuple(args.datasets))
        print(f"{year}: " + ", ".join(f"{k} {v:,}" for k, v in counts.items())
              + f" ({time.monotonic() - started:.0f}s)", flush=True)

    summary = ds.load("fo_summary")
    print("\nData quality")
    for kind in ("participant", "mto", "indices"):
        gaps = [d for d in trading_days if manifest.get((d, kind)) is None or manifest[(d, kind)].status != "ok"]
        print(f"  {kind}: missing on {len(gaps)} F&O trading days" + (f" (e.g. {gaps[:3]})" if gaps else ""))
    per_symbol = summary.groupby("symbol")["trade_date"].nunique()
    short = per_symbol[per_symbol < 0.98 * len(trading_days)]
    print(f"  fo_summary: {len(per_symbol)} of {len(SYMBOLS)} symbols; "
          + (f"short history: {short.to_dict()}" if len(short) else "all present on >=98% of days"))

    if not args.skip_prices:
        prices = fetch_prices()
        prices = merge_nse_indices(prices, ds.load("index_close"))
        prices = fill_stock_gaps(prices, trading_days)
        path = save_prices(prices, trading_days)
        print("  price bars by source:", prices.groupby("source").size().to_dict())
        issues = quality_report(prices, trading_days)
        issues.to_csv(ds.store_root() / "quality_report.csv", index=False)
        print(f"  prices: {prices['symbol'].nunique()} symbols, {len(prices):,} rows -> {path}")
        if len(issues):
            print("  price issues by type:", issues.groupby("issue").size().to_dict())
            print("  most affected:", issues.groupby("symbol").size().nlargest(5).to_dict())
    # 30-day ATM implied vol per symbol, for the agents' quant report (fast to read, slow to compute).
    iv = atm_iv_table(ds.load("option_chain"))
    iv_path = ds.write_parquet(iv, ds.store_root() / "iv" / "iv30.parquet")
    print(f"  implied vol: {len(iv):,} symbol-days -> {iv_path}")
    print(f"\n{SURVIVORSHIP_NOTE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
