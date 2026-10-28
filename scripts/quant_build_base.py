"""Build the stored base (every F&O underlying, +/-25% moneyness, <= 70 days) for some years (docs/PA_34).

    python scripts/quant_build_base.py --years 2015 2016 2017

Reads the raw F&O files already on disk; writes <store>/base_fo_summary/<year>.parquet,
<store>/base_option_chain/<year>.parquet and <store>/base_manifest.json. A file about to be replaced is copied
to <store>/_snapshots/ first. The live datasets are not touched.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()
    started = time.monotonic()
    counts = base_store.build_years(args.years, workers=args.workers)
    for y, c in counts.items():
        print(f"{y}: " + ", ".join(f"{k} {v:,}" for k, v in c.items()))
    print(f"done in {(time.monotonic() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
