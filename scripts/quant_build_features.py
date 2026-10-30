"""Build feature library v1 through the research loader; writes <store>/features_v1/<family>.parquet (docs/PA_42).

    python scripts/quant_build_features.py --part options
    python scripts/quant_build_features.py --part garch
    python scripts/quant_build_features.py --part tables

Signal dates to 2024-12-31 only. Options and GARCH are slow and are kept as intermediate files, so tables can be rebuilt alone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import datastore as ds, trial_log  # noqa: E402
from tradingagents.research import features as fx, gate as g, loader  # noqa: E402

YEARS = range(2010, 2025)


def folder() -> Path:
    p = ds.store_root() / "features_v1"
    p.mkdir(parents=True, exist_ok=True)
    return p


def options_year(year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    chain = loader.load("base_option_chain", start=date(year, 1, 1), end=date(year, 12, 31))[fx.CHAIN_COLUMNS]
    return fx.options_from_chain(loader.european_only(chain))


def run_options(workers: int) -> None:
    t0 = time.monotonic()
    with ProcessPoolExecutor(workers) as pool:
        parts = list(pool.map(options_year, YEARS))
    ds.write_parquet(pd.concat([p[0] for p in parts], ignore_index=True), folder() / "_options.parquet")
    ds.write_parquet(pd.concat([p[1] for p in parts], ignore_index=True), folder() / "_atm.parquet")
    print(f"options {time.monotonic() - t0:.0f}s")


def run_garch(workers: int) -> None:
    t0 = time.monotonic()
    inputs = fx.load_inputs()
    lr = returns_panel(inputs)
    jobs = [(c, lr[c]) for c in lr.columns if lr[c].notna().sum() > fx.GARCH_MIN_RETURNS]
    with ProcessPoolExecutor(workers) as pool:
        parts = [p for p in pool.map(fx.garch_one, jobs, chunksize=4) if len(p)]
    ds.write_parquet(pd.concat(parts, ignore_index=True), folder() / "_garch.parquet")
    print(f"garch {len(parts)} of {len(jobs)} symbols, {time.monotonic() - t0:.0f}s")


def returns_panel(inputs: dict) -> pd.DataFrame:
    f0 = inputs["futures"]
    t = pd.to_datetime(f0["trade_date"])
    sessions = pd.DatetimeIndex(sorted(set(t) | {pd.Timestamp(d) for d in inputs["holes"] if pd.Timestamp(d) <= t.max()}))
    f = fx.contract_panel(f0, sessions)
    near = fx.near_rows(f)
    symbols = pd.Index(sorted(near["symbol"].unique()))
    disc, _ = fx.discontinuities(f, near, inputs["events"], sessions, symbols)
    return fx.source_returns(near, disc, sessions, symbols)


def run_tables() -> None:
    fx.read_spec()
    t0 = time.monotonic()
    inputs = fx.load_inputs()
    options = pd.read_parquet(folder() / "_options.parquet")
    atm = pd.read_parquet(folder() / "_atm.parquet")
    garch = pd.read_parquet(folder() / "_garch.parquet")
    tables, _ = fx.build(inputs, options, atm, garch)
    hashes = {}
    for fam, t in tables.items():
        t = t[pd.to_datetime(t["signal_date"]) <= pd.Timestamp(g.LAST_RESEARCH_DAY)]
        path = folder() / f"{fam}.parquet"
        ds.write_parquet(t, path)
        hashes[fam] = {"rows": len(t), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        print(fam, len(t), flush=True)
    event = trial_log.log_event("data_build", {"dataset": "features_v1", "spec_sha256": fx.SPEC_SHA256, "tables": hashes})
    (ROOT / "reports" / "features").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "features" / "build.json").write_text(json.dumps(hashes, indent=1), encoding="utf-8")
    print(f"tables {time.monotonic() - t0:.0f}s, trial-log event {event}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["options", "garch", "tables"], required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    if args.part == "options":
        run_options(min(args.workers, 3))
    elif args.part == "garch":
        run_garch(args.workers)
    else:
        run_tables()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
