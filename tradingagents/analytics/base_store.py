"""The stored base: every F&O underlying, option chain at the store's filter (docs/PA_34).

Two datasets beside the live store, one Parquet file per year under ``<store>/<dataset>/<year>.parquet``:

- ``base_fo_summary``: one row per (day, underlying), from :func:`datastore.fo_summary` over every symbol in the
  file, plus ``kind`` (index / stock / other), ``lot_source`` (stated in the file, or derived from open interest)
  and ``lot_status``. Every lot before 2018 is ``UNVERIFIED``: derived and not checked against NSE circulars.
- ``base_option_chain``: :func:`datastore.option_chain` (+/-25% moneyness, <= 70 days) over every symbol, with
  two quality flags that never drop a row: ``flag_parity`` (put-call parity off by more than 1% of the forward)
  and ``flag_below_intrinsic`` (a traded close below the discounted intrinsic value by more than
  max(0.05, 0.25% of the forward)). Both use the future of the same expiry as the forward; rows without one are
  not tested (``parity_tested`` / ``intrinsic_tested`` False).

The live datasets (``fo_summary``, ``option_chain``: 31 symbols from 2018) are not touched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.analytics import datastore as ds
from tradingagents.analytics.backfill import load_manifest, raw_path, raw_root
from tradingagents.analytics.implied_vol import DEFAULT_RISK_FREE
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES

SUMMARY, CHAIN = "base_fo_summary", "base_option_chain"
DATASETS = (SUMMARY, CHAIN)
LOTS_VERIFIED_FROM = date(2018, 1, 1)
UNVERIFIED = "UNVERIFIED"
PARITY_TOLERANCE = 0.01             # of the forward
INTRINSIC_TOLERANCE = (0.05, 0.0025)  # rupees, share of the forward: the larger applies
INDEX_INSTRUMENTS = {"FUTIDX", "OPTIDX"}
STOCK_INSTRUMENTS = {"FUTSTK", "OPTSTK"}


def _kind(fo: pd.DataFrame) -> pd.Series:
    inst = fo["instrument"].astype(str).str.strip()
    k = pd.Series(np.where(inst.isin(INDEX_INSTRUMENTS), "index",
                           np.where(inst.isin(STOCK_INSTRUMENTS), "stock", "other")), index=fo.index)
    by = k.groupby(fo["symbol"])
    return by.agg(lambda s: "index" if (s == "index").any() else "stock" if (s == "stock").any() else "other")


def _flags(chain: pd.DataFrame, fo: pd.DataFrame, r: float = DEFAULT_RISK_FREE) -> pd.DataFrame:
    fut = fo[fo["instrument"].isin(ds.FUTURES)][["symbol", "expiry", "close"]].copy()
    fut["close"] = pd.to_numeric(fut["close"], errors="coerce")
    fwd = fut.dropna().drop_duplicates(["symbol", "expiry"]).rename(columns={"close": "forward"})
    c = chain.merge(fwd, on=["symbol", "expiry"], how="left")
    t = (pd.to_datetime(c["expiry"]) - pd.to_datetime(c["trade_date"])).dt.days.clip(lower=0) / 365.0
    disc = np.exp(-r * t)
    traded = (c["contracts"] > 0) & (c["close"] > 0)
    intrinsic = np.where(c["option_type"] == "CE", (c["forward"] - c["strike"]).clip(lower=0),
                         (c["strike"] - c["forward"]).clip(lower=0)) * disc
    tol = np.maximum(INTRINSIC_TOLERANCE[0], INTRINSIC_TOLERANCE[1] * c["forward"])
    c["intrinsic_tested"] = traded & c["forward"].notna()
    c["flag_below_intrinsic"] = c["intrinsic_tested"] & (c["close"] < intrinsic - tol)
    key = ["trade_date", "symbol", "expiry", "strike"]
    calls = c[traded & (c["option_type"] == "CE")].set_index(key)["close"]
    puts = c[traded & (c["option_type"] == "PE")].set_index(key)["close"]
    pair = pd.concat({"call": calls, "put": puts}, axis=1).dropna().reset_index()
    pair = pair.merge(fwd, on=["symbol", "expiry"], how="inner")
    tp = (pd.to_datetime(pair["expiry"]) - pd.to_datetime(pair["trade_date"])).dt.days.clip(lower=0) / 365.0
    dev = (pair["call"] - pair["put"]) - np.exp(-r * tp) * (pair["forward"] - pair["strike"])
    pair["flag_parity"] = dev.abs() > PARITY_TOLERANCE * pair["forward"]
    pair["parity_tested"] = True
    c = c.merge(pair[key + ["parity_tested", "flag_parity"]], on=key, how="left")
    c["parity_tested"] = c["parity_tested"].fillna(False).astype(bool)
    c["flag_parity"] = c["flag_parity"].fillna(False).astype(bool)
    return c.drop(columns="forward")


def build_day(args: tuple[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(summary, chain) for one raw F&O file, every underlying."""
    path, name = args
    fo = ds.parse_fo(Path(path).read_bytes(), name)
    fo["instrument"] = fo["instrument"].astype(str).str.strip()
    symbols = sorted(set(fo["symbol"]))
    summary = ds.fo_summary(fo, symbols)
    stated = summary["lot_size"].notna()
    if (~stated).any():
        lots = ds.lots_from_open_interest(fo)
        summary["lot_size"] = summary["lot_size"].fillna(summary["symbol"].map(lots))
    summary["lot_source"] = np.where(stated, "stated", np.where(summary["lot_size"].notna(), "derived_oi", "none"))
    summary["kind"] = summary["symbol"].map(_kind(fo))
    chain = _flags(ds.option_chain(fo, summary, symbols), fo)
    return summary, chain


def _lot_status(summary: pd.DataFrame) -> pd.Series:
    early = pd.to_datetime(summary["trade_date"]) < pd.Timestamp(LOTS_VERIFIED_FROM)
    return pd.Series(np.where(early, UNVERIFIED, np.where(summary["lot_source"] == "stated", "stated", "derived")),
                     index=summary.index)


def _snapshot(path: Path) -> Path | None:
    """Copy a file about to be replaced, so any count change can be traced to exact rows."""
    if not path.exists():
        return None
    folder = path.parent.parent / "_snapshots" / path.parent.name
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{path.stem}-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}"
    shutil.copy2(path, dest)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_years(years: Iterable[int], raw: Path | None = None, root: Path | None = None,
                workers: int = 4) -> dict[int, dict[str, int]]:
    """Build both datasets for ``years`` from the raw files on disk; returns row counts per year."""
    raw, root = raw or raw_root(), root or ds.store_root()
    manifest = load_manifest(raw)
    ok = {(d, k): r for (d, k), r in manifest.items() if r.status == "ok"}
    trading_days = sorted(d for d, k in ok if k == "fo")
    # the F&O archive holes were sessions: the next session after the day before one is the hole itself
    sessions = ds.next_sessions(set(trading_days) | {d for d, k in ARCHIVE_HOLES.items() if "fo" in k})
    years = sorted(set(years))
    jobs = {y: [(str(raw_path(raw, "fo", d, ok[(d, "fo")].url)), ok[(d, "fo")].url.rsplit("/", 1)[-1])
                for d in trading_days if d.year == y] for y in years}
    built: dict[int, tuple[pd.DataFrame, pd.DataFrame]] = {}
    with ProcessPoolExecutor(workers) as pool:
        for y in years:
            parts = list(pool.map(build_day, jobs[y], chunksize=4))
            built[y] = (pd.concat([p[0] for p in parts], ignore_index=True),
                        pd.concat([p[1] for p in parts], ignore_index=True))
    # despike the derived lots across the whole batch, per symbol (as the live store does)
    summary = pd.concat([built[y][0] for y in years], ignore_index=True).sort_values(["symbol", "trade_date"])
    derived = summary["lot_source"] == "derived_oi"
    despiked = summary[derived].groupby("symbol", group_keys=False)["lot_size"].apply(ds.despike_lots)
    summary.loc[despiked.index, "lot_size"] = despiked.to_numpy()
    summary["lot_status"] = _lot_status(summary)
    counts = {}
    for y in years:
        s = summary[pd.to_datetime(summary["trade_date"]).dt.year == y].sort_values(["trade_date", "symbol"])
        c = built[y][1]
        out = {}
        for name, df in ((SUMMARY, s), (CHAIN, c)):
            df = ds.add_known_from(df.reset_index(drop=True), sessions)
            path = root / name / f"{y}.parquet"
            _snapshot(path)
            ds.write_parquet(df, path)
            out[name] = len(df)
        counts[y] = out
    write_manifest(root, raw, ok)
    return counts


def write_manifest(root: Path, raw: Path, ok: dict) -> Path:
    """Per dataset and year: rows, date range, checksum, source and download dates."""
    entries = {}
    for name in DATASETS:
        for f in sorted((root / name).glob("*.parquet")):
            y = int(f.stem)
            df = pd.read_parquet(f, columns=["trade_date"])
            fetched = [r.fetched_at for (d, k), r in ok.items() if k == "fo" and d.year == y]
            entries.setdefault(name, {})[y] = {
                "rows": len(df), "min_date": str(df["trade_date"].min()), "max_date": str(df["trade_date"].max()),
                "sha256": sha256(f), "bytes": f.stat().st_size,
                "source": "NSE F&O bhavcopy (nsearchives.nseindia.com /content/historical/DERIVATIVES/... legacy, "
                          "/content/fo/BhavCopy_NSE_FO_... UDiFF)",
                "downloaded": [min(fetched), max(fetched)] if fetched else None,
                "built_at": datetime.now().isoformat(timespec="seconds"),
            }
    path = root / "base_manifest.json"
    path.write_text(json.dumps(entries, indent=1, sort_keys=True), encoding="utf-8")
    return path


def load(name: str, years: Iterable[int] | None = None, symbols: Iterable[str] | None = None,
         root: Path | None = None) -> pd.DataFrame:
    if name not in DATASETS:
        raise ValueError(f"unknown dataset {name!r}; one of {DATASETS}")
    files = sorted(((root or ds.store_root()) / name).glob("*.parquet"))
    if years is not None:
        files = [f for f in files if int(f.stem) in set(years)]
    if not files:
        return pd.DataFrame()
    filters = [("symbol", "in", sorted(set(symbols)))] if symbols is not None else None
    return pd.concat((pd.read_parquet(f, filters=filters) for f in files), ignore_index=True)
