"""The only door from research code to the NSE store: point-in-time checked, holdouts locked.

- **Point in time.** Every row must carry ``known_from`` (the first session it was public), strictly after its
  ``trade_date``. A dataset without the column is refused, and a row that breaks the rule fails the whole load.
- **Periods by ``known_from``.** ``start`` / ``end`` select rows by the day they became public, so a backtest
  ending on the validation set's last day never sees a row first public in the holdout.
- **Locked holdouts.** A range touching ``final_holdout`` needs ``Unlock("final_holdout", reason)``; one touching
  ``forward_holdout`` also needs a pre-registration file committed to git and unmodified. Each unlock is written
  to the trial log *before* any row is read; if that write fails, nothing is returned.
- **Counts only.** :func:`holdout_counts` gives rows per day in the locked periods (data-quality counts) with no
  values and no unlock.

The live pipeline (nightly refresh, paper trading, web app) keeps using ``analytics.datastore`` directly.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.analytics import datastore as ds, trial_log
from tradingagents.research import splits

# Derived tables that carry known_from, beside the store's own datasets.
DERIVED = {"prices": ("prices", "prices.parquet"), "iv30": ("iv", "iv30.parquet"), "regime": ("regime", "regime.parquet")}
DATASETS = ds.DATASETS + tuple(DERIVED)
REFUSED = {
    "vol_forecasts": "has no known_from column; stamp it before research code may read it",
    "chronos": "has no known_from column; stamp it before research code may read it",
}

# known_from can trail trade_date by a long holiday weekend (e.g. 2021-03-26 -> 2021-03-31 over an archive
# hole); read this much earlier by trade_date so no row known inside the range is missed.
_LOOKBACK = timedelta(days=31)

REPO_ROOT = Path(__file__).resolve().parents[2]


class HoldoutLocked(PermissionError):
    """The request touches a locked period without a valid unlock."""


class PointInTimeError(ValueError):
    """A row has no known_from, or one not strictly after its trade_date."""


@dataclass(frozen=True)
class Unlock:
    period: str
    reason: str
    preregistration: Path | None = None


def check_point_in_time(df: pd.DataFrame, dataset: str) -> None:
    if not len(df):
        return
    if "known_from" not in df or "trade_date" not in df:
        raise PointInTimeError(f"{dataset}: needs trade_date and known_from columns")
    known, traded = pd.to_datetime(df["known_from"]), pd.to_datetime(df["trade_date"])
    if known.isna().any():
        raise PointInTimeError(f"{dataset}: {int(known.isna().sum())} rows without known_from")
    early = known <= traded
    if early.any():
        raise PointInTimeError(f"{dataset}: {int(early.sum())} rows public on or before their own session, "
                               f"e.g. trade_date {traded[early].iloc[0].date()}")


def _committed(path: Path) -> bool:
    """Tracked by git with no uncommitted change."""
    rel = str(Path(path).resolve().relative_to(REPO_ROOT))
    run = {"cwd": REPO_ROOT, "capture_output": True}
    return (subprocess.run(["git", "ls-files", "--error-unmatch", rel], **run).returncode == 0
            and subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], **run).returncode == 0)


def _grant(period: splits.Period, unlocks: dict[str, Unlock]) -> dict:
    u = unlocks.get(period.name)
    if u is None:
        raise HoldoutLocked(f"range touches {period.name} ({period.label}); pass Unlock({period.name!r}, reason)")
    if not u.reason.strip():
        raise HoldoutLocked(f"unlocking {period.name} needs a reason")
    entry = {"period": period.name, "label": period.label, "reason": u.reason}
    if period.access == splits.PREREGISTERED:
        p = Path(u.preregistration) if u.preregistration else None
        if p is None or not p.is_file():
            raise HoldoutLocked(f"{period.name} opens only for a pre-registered test: pass its spec file")
        if not _committed(p):
            raise HoldoutLocked(f"pre-registration {p} must be committed to git and unmodified")
        entry |= {"preregistration": str(p), "preregistration_sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    return entry


def _read(dataset: str, start: date | None, end: date | None, symbols: Iterable[str] | None,
          root: Path | None) -> pd.DataFrame:
    if dataset in ds.DATASETS:
        return ds.load(dataset, start, end, symbols, root)
    folder, name = DERIVED[dataset]
    df = pd.read_parquet((root or ds.store_root()) / folder / name)
    traded = pd.to_datetime(df["trade_date"])
    keep = pd.Series(True, index=df.index)
    if start:
        keep &= traded >= pd.Timestamp(start)
    if end:
        keep &= traded <= pd.Timestamp(end)
    if symbols is not None and "symbol" in df:
        keep &= df["symbol"].isin(set(symbols))
    return df[keep].reset_index(drop=True)


def load(dataset: str, start: date | None = None, end: date | None = None, symbols: Iterable[str] | None = None,
         unlocks: Sequence[Unlock] = (), root: Path | None = None, log_path: Path | None = None) -> pd.DataFrame:
    """Rows of ``dataset`` first public between ``start`` and ``end`` (by ``known_from``, both inclusive).

    ``end`` defaults to the last open day (the validation set's end), so a call without unlocks never
    reaches a holdout.
    """
    if dataset in REFUSED:
        raise PointInTimeError(f"{dataset}: {REFUSED[dataset]}")
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; one of {DATASETS}")
    end = end or splits.last_open_day()
    if start and start > end:
        raise ValueError(f"start {start} is after end {end}")
    granted = {u.period: u for u in unlocks}
    touched = [p for p in splits.periods().values() if p.locked and p.overlaps(start, end)]
    entries = [_grant(p, granted) for p in touched]
    for entry in entries:     # written before any row is read
        trial_log.log_event("holdout_unlock", entry | {"dataset": dataset, "start": start, "end": end,
                                                       "symbols": sorted(symbols) if symbols else None},
                            log_path)
    df = _read(dataset, start - _LOOKBACK if start else None, end, symbols, root)
    check_point_in_time(df, dataset)
    if not len(df):
        return df
    known = pd.to_datetime(df["known_from"])
    keep = known <= pd.Timestamp(end)
    if start:
        keep &= known >= pd.Timestamp(start)
    return df[keep].reset_index(drop=True)


def holdout_counts(dataset: str, symbols: Iterable[str] | None = None, root: Path | None = None) -> pd.DataFrame:
    """Rows per ``known_from`` day in each locked period: counts only, for data-quality checks."""
    if dataset not in DATASETS:
        raise ValueError(f"unknown dataset {dataset!r}; one of {DATASETS}")
    locked = [p for p in splits.periods().values() if p.locked]
    first = min(p.start for p in locked)
    df = _read(dataset, first - _LOOKBACK, None, symbols, root)
    if not len(df):
        return pd.DataFrame(columns=["period", "known_from", "rows"])
    known = pd.to_datetime(df["known_from"]).dt.date
    out = known[known >= first].value_counts().sort_index().rename_axis("known_from").reset_index(name="rows")
    out.insert(0, "period", [splits.period_of(d).name for d in out["known_from"]])
    return out
