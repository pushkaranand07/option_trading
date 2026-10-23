"""Point-in-time Parquet store built from the raw NSE archive files (plan, Phase 1).

Every row carries ``trade_date`` (the session it describes) and ``known_from``
(the first session on which a trader could have used it). NSE publishes these
files after the close, so ``known_from`` is the next trading session. Anything
that drives a decision on day *t* must use only rows with ``known_from <= t``;
:func:`as_of` does that filtering.

Datasets (``<data_cache_dir>/quant/store/<dataset>/<year>.parquet``):

- ``fo_summary``   one row per (day, symbol): futures OI/price, option OI, PCR
- ``option_chain`` near-dated option contracts for the universe (for IV and backtests)
- ``participant``  FII / DII / Pro / Client open interest by contract type
- ``delivery``     traded and deliverable quantity, delivery % per stock

Raw files are parsed as NSE published them; nothing here calls the network.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.analytics.backfill import load_manifest, raw_path, raw_root
from tradingagents.analytics.universe import SYMBOLS
from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.vendors.nse.derivatives import (
    _unzip_csv,
    derive_legacy_lot_sizes,
    normalize_legacy,
    normalize_udiff,
)

DATASETS = ("fo_summary", "option_chain", "participant", "delivery")

# Option contracts further out than this, or strikes further than this from the
# underlying, are dropped from the stored chain: illiquid and never traded here.
CHAIN_MAX_DAYS = 70
CHAIN_MAX_MONEYNESS = 0.25

FUTURES = {"FUTIDX", "FUTSTK"}
OPTIONS = {"OPTIDX", "OPTSTK"}

PARTICIPANT_COLUMNS = [
    "fut_idx_long", "fut_idx_short", "fut_stk_long", "fut_stk_short",
    "opt_idx_call_long", "opt_idx_put_long", "opt_idx_call_short", "opt_idx_put_short",
    "opt_stk_call_long", "opt_stk_put_long", "opt_stk_call_short", "opt_stk_put_short",
    "total_long", "total_short",
]


# ---------------------------------------------------------------- parsers

def parse_fo(raw: bytes, filename: str) -> pd.DataFrame:
    """F&O bhavcopy in the unified schema of ``derivatives.py``, either format."""
    table = _unzip_csv(raw)
    return normalize_udiff(table) if filename.startswith("BhavCopy_") else normalize_legacy(table)


def parse_participant(raw: bytes, day: date) -> pd.DataFrame:
    """Participant-wise OI: one row per category (Client, DII, FII, Pro, TOTAL).

    ``day`` comes from the file name: some files have an "as on <date>" title
    line (month short or in full), some start straight at the header. When the
    title is there it must agree with ``day``.
    """
    text = raw.decode("utf-8", errors="replace")
    match = re.search(r"as on ([A-Za-z]{3})[A-Za-z]* (\d{1,2}), (\d{4})", text)
    if match:
        titled = datetime.strptime(" ".join(match.groups()), "%b %d %Y").date()
        if titled != day:
            raise ValueError(f"participant OI file for {day} says it is for {titled}")
    lines = text.splitlines()
    header = next((i for i, line in enumerate(lines) if line.strip().lower().startswith("client type")), None)
    if header is None:
        raise ValueError(f"participant OI file for {day} has no 'Client Type' header")
    table = pd.read_csv(io.StringIO("\n".join(lines[header:])))
    table = table.dropna(subset=[table.columns[0]])
    out = pd.DataFrame({"trade_date": day, "category": table.iloc[:, 0].astype(str).str.strip()})
    for i, name in enumerate(PARTICIPANT_COLUMNS, start=1):
        values = pd.to_numeric(table.iloc[:, i].astype(str).str.replace(",", "").str.strip(), errors="coerce")
        out[name] = values.round().astype("Int64")
    return out.reset_index(drop=True)


def parse_mto(raw: bytes) -> pd.DataFrame:
    """Security-wise delivery position. Data rows (record type 20) have a series
    column that the header line leaves out."""
    lines = raw.decode("utf-8", errors="replace").splitlines()
    day = None
    rows = []
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3 and parts[0] == "10" and parts[1] == "MTO":
            day = datetime.strptime(parts[2], "%d%m%Y").date()
        elif parts[0] == "20" and len(parts) >= 7:
            rows.append(parts[2:7])
    if day is None:
        raise ValueError("MTO file without a '10,MTO,<date>' header")
    df = pd.DataFrame(rows, columns=["symbol", "series", "traded_qty", "deliverable_qty", "deliv_pct"])
    for col in ("traded_qty", "deliverable_qty"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df["deliv_pct"] = pd.to_numeric(df["deliv_pct"], errors="coerce")
    df.insert(0, "trade_date", day)
    return df


# ---------------------------------------------------------------- derived tables

def fo_summary(fo: pd.DataFrame, symbols: Iterable[str] = SYMBOLS) -> pd.DataFrame:
    """Per (day, symbol): near-month future, total futures OI, option OI and put/call ratios."""
    fo = fo[fo["symbol"].isin(set(symbols))]
    out = []
    for (day, symbol), g in fo.groupby(["trade_date", "symbol"], sort=True):
        fut = g[g["instrument"].isin(FUTURES)].sort_values("expiry")
        opt = g[g["instrument"].isin(OPTIONS)]
        calls, puts = opt[opt["option_type"] == "CE"], opt[opt["option_type"] == "PE"]
        near = fut.iloc[0] if len(fut) else None
        underlying = pd.to_numeric(g["underlying_price"], errors="coerce").dropna()
        lots = pd.to_numeric(fut["lot_size"], errors="coerce").dropna()
        call_oi, put_oi = float(calls["open_interest"].sum()), float(puts["open_interest"].sum())
        call_vol, put_vol = float(calls["contracts"].sum()), float(puts["contracts"].sum())
        out.append({
            "trade_date": day,
            "symbol": symbol,
            "near_expiry": near["expiry"] if near is not None else pd.NaT,
            "fut_close": float(near["close"]) if near is not None else np.nan,
            "fut_settle": float(near["settle"]) if near is not None else np.nan,
            "underlying_price": float(underlying.iloc[0]) if len(underlying) else np.nan,
            "fut_oi": float(fut["open_interest"].sum()),
            "fut_oi_change": float(fut["oi_change"].sum()),
            "fut_contracts": float(fut["contracts"].sum()),
            "fut_turnover": float(fut["turnover"].sum()),
            "call_oi": call_oi,
            "put_oi": put_oi,
            "pcr_oi": put_oi / call_oi if call_oi else np.nan,
            "call_contracts": call_vol,
            "put_contracts": put_vol,
            "pcr_volume": put_vol / call_vol if call_vol else np.nan,
            "opt_turnover": float(opt["turnover"].sum()),
            # The new format states the lot; for the old one build_year derives it.
            "lot_size": float(lots.iloc[0]) if len(lots) else np.nan,
        })
    return pd.DataFrame(out)


def option_chain(fo: pd.DataFrame, summary: pd.DataFrame, symbols: Iterable[str] = SYMBOLS) -> pd.DataFrame:
    """Option contracts within ``CHAIN_MAX_DAYS`` and ``CHAIN_MAX_MONEYNESS`` of the money.

    Moneyness is measured against the reported underlying, or the near-month
    future where the old format did not report one.
    """
    opt = fo[fo["symbol"].isin(set(symbols)) & fo["instrument"].isin(OPTIONS)].copy()
    if opt.empty:
        return opt
    ref = summary.set_index(["trade_date", "symbol"])
    ref = ref["underlying_price"].fillna(ref["fut_close"]).rename("ref_price")
    opt = opt.join(ref, on=["trade_date", "symbol"])
    days = (pd.to_datetime(opt["expiry"]) - pd.to_datetime(opt["trade_date"])).dt.days
    moneyness = (opt["strike"] / opt["ref_price"] - 1.0).abs()
    keep = (days >= 0) & (days <= CHAIN_MAX_DAYS) & (moneyness <= CHAIN_MAX_MONEYNESS)
    cols = ["trade_date", "symbol", "instrument", "expiry", "strike", "option_type", "open", "high", "low",
            "close", "settle", "open_interest", "oi_change", "contracts", "turnover", "ref_price"]
    chain = opt.loc[keep, cols].reset_index(drop=True)
    for col in ("open", "high", "low", "close", "settle", "open_interest", "oi_change", "contracts", "turnover",
                "ref_price", "strike"):
        chain[col] = pd.to_numeric(chain[col], errors="coerce").astype(float)
    return chain


# ---------------------------------------------------------------- point in time

def next_sessions(trading_days: Iterable[date]) -> dict[date, date]:
    """Each trading day mapped to the following one; the last maps to the next weekday."""
    days = sorted(set(trading_days))
    mapping = {d: n for d, n in zip(days, days[1:])}
    if days:
        nxt = days[-1] + timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt += timedelta(days=1)
        mapping[days[-1]] = nxt
    return mapping


def add_known_from(df: pd.DataFrame, sessions: dict[date, date]) -> pd.DataFrame:
    df = df.copy()
    df["known_from"] = df["trade_date"].map(sessions)
    return df


def as_of(df: pd.DataFrame, t: date | pd.Timestamp) -> pd.DataFrame:
    """Only the rows a trader could have seen at the start of session ``t``."""
    return df[df["known_from"] <= pd.Timestamp(t).date()]


# ---------------------------------------------------------------- build / load

def store_root() -> Path:
    return Path(get_config()["data_cache_dir"]) / "quant" / "store"


def _write(df: pd.DataFrame, root: Path, dataset: str, year: int) -> Path:
    path = root / dataset / f"{year}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def build_year(year: int, raw: Path | None = None, root: Path | None = None) -> dict[str, int]:
    """Parse one year's raw files into the four datasets. Returns row counts."""
    raw = raw or raw_root()
    root = root or store_root()
    manifest = load_manifest(raw)
    ok = {(d, k): r for (d, k), r in manifest.items() if r.status == "ok"}
    trading_days = sorted(d for d, k in ok if k == "fo")
    sessions = next_sessions(trading_days)
    year_days = [d for d in trading_days if d.year == year]

    summaries, chains, participants, deliveries = [], [], [], []
    for day in year_days:
        fo_row = ok[(day, "fo")]
        fo = parse_fo(raw_path(raw, "fo", day, fo_row.url).read_bytes(), fo_row.url.rsplit("/", 1)[-1])
        summary = fo_summary(fo)
        if summary["lot_size"].isna().any():
            derived = derive_legacy_lot_sizes(fo)
            summary["lot_size"] = summary["lot_size"].fillna(summary["symbol"].map(derived))
        summaries.append(summary)
        chains.append(option_chain(fo, summary))
        if (day, "participant") in ok:
            r = ok[(day, "participant")]
            participants.append(parse_participant(raw_path(raw, "participant", day, r.url).read_bytes(), day))
        if (day, "mto") in ok:
            r = ok[(day, "mto")]
            mto = parse_mto(raw_path(raw, "mto", day, r.url).read_bytes())
            deliveries.append(mto[(mto["series"] == "EQ") & mto["symbol"].isin(SYMBOLS)])

    counts = {}
    for name, parts in (("fo_summary", summaries), ("option_chain", chains),
                        ("participant", participants), ("delivery", deliveries)):
        parts = [p for p in parts if len(p)]
        if not parts:
            counts[name] = 0
            continue
        df = add_known_from(pd.concat(parts, ignore_index=True), sessions)
        _write(df, root, name, year)
        counts[name] = len(df)
    return counts


def load(dataset: str, start: date | None = None, end: date | None = None,
         symbols: Iterable[str] | None = None, root: Path | None = None) -> pd.DataFrame:
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; one of {DATASETS}")
    folder = (root or store_root()) / dataset
    files = sorted(folder.glob("*.parquet"))
    if start or end:
        files = [f for f in files
                 if (not start or int(f.stem) >= start.year) and (not end or int(f.stem) <= end.year)]
    if not files:
        return pd.DataFrame()
    df = pd.concat((pd.read_parquet(f) for f in files), ignore_index=True)
    if start:
        df = df[df["trade_date"] >= start]
    if end:
        df = df[df["trade_date"] <= end]
    if symbols is not None and "symbol" in df:
        df = df[df["symbol"].isin(set(symbols))]
    return df.reset_index(drop=True)
