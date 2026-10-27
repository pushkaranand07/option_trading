"""Apply the session rule to the stored prices without refetching Yahoo (docs/PA_32).

    python scripts/quant_fix_price_sessions.py --dry-run
    python scripts/quant_fix_price_sessions.py

Removes bars dated on days with no NSE session (never replaced) and re-stamps known_from as the next session.
Prints row counts and dates only, no prices: the affected rows may sit in a locked holdout. A run that changes
rows is written to the trial log as a data correction; a run that changes nothing writes nothing.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.analytics.backfill import load_manifest, raw_root  # noqa: E402
from tradingagents.analytics.datastore import add_known_from, next_sessions, write_parquet  # noqa: E402
from tradingagents.analytics.prices import drop_non_sessions, price_sessions, prices_path  # noqa: E402
from tradingagents.research import splits  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = prices_path()
    old = pd.read_parquet(path)
    trading_days = sorted(d for (d, k), r in load_manifest(raw_root()).items() if k == "fo" and r.status == "ok")
    sessions = price_sessions(trading_days, old["trade_date"])
    kept, dropped = drop_non_sessions(old, sessions)
    new = add_known_from(kept.drop(columns="known_from"), next_sessions(sessions))
    changed = new[pd.to_datetime(new["known_from"]) != pd.to_datetime(kept["known_from"])]

    by_day = dropped.groupby("trade_date").size().to_dict()
    restamped = changed.groupby("trade_date").size().to_dict()
    print(f"prices: {len(old):,} rows -> {len(new):,}")
    print(f"  bars removed (no NSE session): {len(dropped)} {by_day}")
    print(f"  known_from corrected: {len(changed)} rows, by trade_date {restamped}")
    if not len(dropped) and not len(changed):
        print("Nothing to correct.")
        return 0
    if args.dry_run:
        print("Dry run: nothing written.")
        return 0

    write_parquet(new, path)
    days = sorted(set(by_day) | set(restamped))
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1]).stdout.strip()
    event = trial_log.log_event("data_correction", {
        "dataset": "prices",
        "rule": "bars only on NSE sessions; known_from = next session (prices.price_sessions)",
        "rows_before": len(old), "rows_after": len(new),
        "bars_removed": len(dropped), "bars_removed_by_date": by_day,
        "known_from_corrected": len(changed), "known_from_corrected_by_trade_date": restamped,
        "periods": sorted({splits.period_of(d).name for d in days}),
        "values_inspected": False, "code": commit,
    })
    print(f"Written {path}; trial-log data_correction event {event}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
