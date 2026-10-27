"""Count the whole F&O universe in the raw bhavcopies, before anything is ingested (docs/PA_33).

    python scripts/quant_count_fo_universe.py                       # every raw F&O file in the store's raw folder
    python scripts/quant_count_fo_universe.py --sample-dir <dir>    # plus sample files (e.g. 2010-2014), flagged

Parses each file with the store's own parser and, per (day, underlying), records option rows under a grid of
moneyness / days-to-expiry filters (the store's reference price: NSE's underlying price, else the near-month
future close), F&O turnover for liquidity ranking, whether a lot size is stated (UDiFF) or derivable from open
interest (legacy), and the option expiries listed. Writes <out>/per_symbol_day.parquet and <out>/files.csv.
Reads raw files only; writes nothing to the store.
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds  # noqa: E402
from tradingagents.analytics.backfill import raw_root  # noqa: E402

MONEYNESS = (0.10, 0.15, 0.25, None)        # None: no moneyness filter
DAYS = (35, 70, None)                       # None: every expiry
INDEX_INSTRUMENTS = {"FUTIDX", "OPTIDX"}
STOCK_INSTRUMENTS = {"FUTSTK", "OPTSTK"}


def grid_name(m: float | None, d: int | None) -> str:
    return f"m{'all' if m is None else int(round(m * 100))}_d{'all' if d is None else d}"


def count_file(args: tuple[str, bool]) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    path, sample = args
    p = Path(path)
    fo = ds.parse_fo(p.read_bytes(), p.name)
    day = fo["trade_date"].iloc[0]
    fo["instrument"] = fo["instrument"].astype(str).str.strip()
    for col in ("close", "underlying_price", "open_interest", "turnover", "lot_size"):
        fo[col] = pd.to_numeric(fo[col], errors="coerce")
    kind = np.where(fo["instrument"].isin(INDEX_INSTRUMENTS), "index",
                    np.where(fo["instrument"].isin(STOCK_INSTRUMENTS), "stock", "other"))
    fo["kind"] = kind
    fut = fo[fo["instrument"].isin(ds.FUTURES)].sort_values("expiry")
    near_close = fut.groupby("symbol")["close"].first()
    ref = fo.groupby("symbol")["underlying_price"].first().fillna(near_close)
    opt = fo[fo["instrument"].isin(ds.OPTIONS)].copy()
    opt["ref"] = opt["symbol"].map(ref)
    dte = (pd.to_datetime(opt["expiry"]) - pd.to_datetime(opt["trade_date"])).dt.days
    money = (opt["strike"] / opt["ref"] - 1.0).abs()
    for m in MONEYNESS:
        for d in DAYS:
            keep = dte >= 0
            if d is not None:
                keep &= dte <= d
            if m is not None:
                keep &= money <= m
            opt[grid_name(m, d)] = keep.astype(np.int32)
    grids = [grid_name(m, d) for m in MONEYNESS for d in DAYS]
    per = opt.groupby("symbol")[grids].sum()
    per["no_ref"] = opt[opt["ref"].isna()].groupby("symbol").size()
    per["expiries"] = opt.groupby("symbol")["expiry"].nunique()
    out = pd.DataFrame(index=pd.Index(sorted(set(fo["symbol"])), name="symbol"))
    out["kind"] = fo.groupby("symbol")["kind"].agg(lambda k: "index" if (k == "index").any()
                                                    else "stock" if (k == "stock").any() else "other")
    out["turnover"] = fo.groupby("symbol")["turnover"].sum()
    out["has_options"] = out.index.isin(opt["symbol"].unique())
    out = out.join(per)
    fmt = fo["format"].iloc[0]
    if fmt == "udiff":
        out["lot_stated"] = fut.groupby("symbol")["lot_size"].first().reindex(out.index).notna()
        out["lot_derived"] = False
    else:
        derived = ds.lots_from_open_interest(fo)
        out["lot_stated"] = False
        out["lot_derived"] = out.index.isin([s for s, v in derived.items() if v and v > 0])
    out = out.fillna({"no_ref": 0, "expiries": 0, **dict.fromkeys(grids, 0)}).reset_index()
    out.insert(0, "trade_date", day)
    # Expiry calendar: each index's option expiries listed that day, and the stocks' pooled
    group = np.where(opt["kind"] == "index", opt["symbol"], "STOCKS")
    expiries = (pd.DataFrame({"group": group, "expiry": opt["expiry"]}).drop_duplicates()
                .assign(trade_date=day))
    meta = {"path": p.name, "trade_date": day, "bytes": p.stat().st_size, "format": fmt, "rows": len(fo),
            "option_rows": len(opt), "sample": sample}
    return meta, out, expiries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sample-dir", type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "reports" / "fo_count")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = parser.parse_args()

    jobs = [(str(f), False) for f in sorted((raw_root() / "fo").rglob("*.zip"))]
    if args.sample_dir:
        jobs += [(str(f), True) for f in sorted(args.sample_dir.glob("*.zip"))]
    print(f"{len(jobs)} files ({sum(s for _, s in jobs)} sample), {args.workers} workers", flush=True)
    metas, frames, expiries = [], [], []
    with ProcessPoolExecutor(args.workers) as pool:
        for i, (meta, frame, exp) in enumerate(pool.map(count_file, jobs, chunksize=8), 1):
            metas.append(meta)
            frames.append(frame.assign(sample=meta["sample"]))
            expiries.append(exp.assign(sample=meta["sample"]))
            if i % 250 == 0:
                print(f"  {i}/{len(jobs)}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_parquet(args.out / "per_symbol_day.parquet", index=False)
    pd.concat(expiries, ignore_index=True).to_parquet(args.out / "expiries.parquet", index=False)
    pd.DataFrame(metas).sort_values("trade_date").to_csv(args.out / "files.csv", index=False)
    print(f"Wrote per_symbol_day.parquet, expiries.parquet and files.csv to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
