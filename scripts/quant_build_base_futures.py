"""Build base_futures: every futures contract per session, 2010-2024, from the raw files on disk (docs/PA_39).

    python scripts/quant_build_base_futures.py

base_fo_summary has no futures open, and the gate's entry is the open. Prices are stored as NSE reports them: nothing
is adjusted. Years after 2024 are refused: this table is built for the gate, which may not read the locked range.
Writes <store>/base_futures/<year>.parquet and <store>/base_futures_manifest.json; logs a trial-log data_build.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store as bs, datastore as ds, trial_log  # noqa: E402
from tradingagents.analytics.backfill import load_manifest, raw_path, raw_root  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES  # noqa: E402

YEARS = range(2010, 2025)
NAME = "base_futures"
COLUMNS = ["trade_date", "symbol", "instrument", "expiry", "open", "high", "low", "close", "settle", "open_interest",
           "oi_change", "contracts", "turnover"]


def one_day(args: tuple[str, str]) -> pd.DataFrame:
    path, name = args
    fo = bs.parse_fo_with_style(Path(path).read_bytes(), name)
    fo["instrument"] = fo["instrument"].astype(str).str.strip()
    fut = fo[fo["instrument"].isin(ds.FUTURES)][COLUMNS].copy()
    for c in COLUMNS[4:]:
        fut[c] = pd.to_numeric(fut[c], errors="coerce").astype(float)
    return fut


def main() -> int:
    raw, root = raw_root(), ds.store_root()
    ok = {(d, k): r for (d, k), r in load_manifest(raw).items() if r.status == "ok"}
    days = sorted(d for d, k in ok if k == "fo")
    sessions = ds.next_sessions(set(days) | {d for d, k in ARCHIVE_HOLES.items() if "fo" in k})
    out = {}
    with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 2)) as pool:
        for y in YEARS:
            jobs = [(str(raw_path(raw, "fo", d, ok[(d, "fo")].url)), ok[(d, "fo")].url.rsplit("/", 1)[-1])
                    for d in days if d.year == y]
            df = pd.concat(pool.map(one_day, jobs, chunksize=8), ignore_index=True)
            df = ds.add_known_from(df, sessions)
            path = root / NAME / f"{y}.parquet"
            bs._snapshot(path)
            ds.write_parquet(df, path)
            dup = int(df.duplicated(["trade_date", "symbol", "instrument", "expiry"]).sum())
            out[str(y)] = {"rows": len(df), "bytes": path.stat().st_size, "sha256": bs.sha256(path), "duplicate_keys": dup,
                           "min_date": str(df["trade_date"].min()), "max_date": str(df["trade_date"].max()),
                           "built_at": datetime.now().isoformat(timespec="seconds")}
            print(y, f"{len(df):,} rows, {path.stat().st_size / 1e6:.1f} MB, duplicate keys {dup}", flush=True)
    (root / "base_futures_manifest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    event = trial_log.log_event("data_build", {"dataset": NAME, "years": "2010-2024", "rows": {y: v["rows"] for y, v in out.items()},
                                               "bytes": {y: v["bytes"] for y, v in out.items()}, "periods": ["development", "validation"]})
    print("total", f"{sum(v['rows'] for v in out.values()):,}", "| trial-log event", event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
