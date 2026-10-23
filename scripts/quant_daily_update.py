"""After-close refresh of the whole quant layer (plan, Phase 10 groundwork).

    python scripts/quant_daily_update.py              # run every step
    python scripts/quant_daily_update.py --dry-run    # print the steps only

Steps, in order; the first failure stops the run (later steps would build on
stale or half-built data):

1. download the last 10 days' NSE files, re-checking days marked missing
   (a run before NSE publishes would otherwise mark today missing for good)
2. rebuild the current year's store, prices, quality report and implied vol
3. GARCH / EWMA volatility forecasts
4. market regime
5. progress tracker bars

Writes <data_cache_dir>/quant/daily_status.json with each step's outcome and
time. Run it after about 19:00 IST, when NSE has published the day's files.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def steps(today: date) -> list[tuple[str, list[str]]]:
    start = (today - timedelta(days=10)).isoformat()
    yesterday = (today - timedelta(days=1)).isoformat()
    end = today.isoformat() if datetime.now().hour >= 19 else yesterday
    return [
        ("download", ["scripts/quant_backfill.py", "--start", start, "--end", end, "--retry-missing"]),
        ("store", ["scripts/quant_build_store.py", "--years", str(today.year)]),
        ("volatility", ["scripts/quant_vol_forecasts.py"]),
        ("regime", ["scripts/quant_regime.py"]),
        ("tracker", ["scripts/update_progress.py"]),
    ]


def run_steps(plan: list[tuple[str, list[str]]], runner: Callable[[list[str]], int]) -> list[dict]:
    """Run each step; stop at the first non-zero exit. Returns one record per step attempted."""
    records = []
    for name, args in plan:
        started = time.monotonic()
        code = runner(args)
        records.append({"step": name, "exit_code": code, "seconds": round(time.monotonic() - started, 1)})
        if code != 0:
            break
    return records


def _subprocess_runner(args: list[str]) -> int:
    print(f"\n=== {' '.join(args)}", flush=True)
    return subprocess.run([sys.executable, "-W", "ignore", *args], cwd=ROOT).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    plan = steps(date.today())
    if args.dry_run:
        for name, cmd in plan:
            print(f"{name:>10}: python {' '.join(cmd)}")
        return 0

    from tradingagents.dataflows.config import get_config

    started = datetime.now().isoformat(timespec="seconds")
    records = run_steps(plan, _subprocess_runner)
    ok = len(records) == len(plan) and all(r["exit_code"] == 0 for r in records)
    status = {"started": started, "finished": datetime.now().isoformat(timespec="seconds"),
              "ok": ok, "steps": records}
    path = Path(get_config()["data_cache_dir"]) / "quant" / "daily_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(status, indent=1), encoding="utf-8")
    print(f"\nDaily update {'finished' if ok else 'STOPPED at ' + records[-1]['step']} -> {path}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
