"""Download NSE archive history for the quant signal layer (plan, Phase 1).

    python scripts/quant_backfill.py                       # 2018-01-01 to yesterday, all kinds
    python scripts/quant_backfill.py --start 2024-01-01 --kinds fo
    python scripts/quant_backfill.py --retry-missing       # re-check days marked missing

Slow on purpose (one request every --interval seconds) so NSE does not block
the IP. Safe to stop with Ctrl+C and run again: finished days are skipped.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics.backfill import KINDS, backfill, raw_root  # noqa: E402
from tradingagents.analytics.universe import HISTORY_START  # noqa: E402
from tradingagents.dataflows.vendors.nse.client import NSEClient  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=date.fromisoformat, default=HISTORY_START)
    parser.add_argument("--end", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--kinds", nargs="+", choices=KINDS, default=list(KINDS))
    parser.add_argument("--interval", type=float, default=1.5, help="seconds between requests")
    parser.add_argument("--retry-missing", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    root = raw_root()
    print(f"Raw files: {root}\nRange: {args.start} to {args.end}, kinds: {', '.join(args.kinds)}", flush=True)

    started = time.monotonic()
    last_month = None

    def progress(day, stats):
        nonlocal last_month
        if (day.year, day.month) != last_month:
            last_month = (day.year, day.month)
            minutes = (time.monotonic() - started) / 60
            print(f"{day:%Y-%m}: fetched {stats.fetched}, missing {stats.missing}, "
                  f"already had {stats.skipped} ({minutes:.0f} min)", flush=True)

    client = NSEClient(min_interval=args.interval)
    stats = backfill(client, args.start, args.end, args.kinds, root, args.retry_missing, progress)
    print(f"Done: fetched {stats.fetched}, missing {stats.missing}, already had {stats.skipped}.")
    if stats.stopped_early:
        print(f"Stopped early, NSE unavailable at {stats.stopped_early}. Run again later to resume.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
