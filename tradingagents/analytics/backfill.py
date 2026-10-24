"""One-time, resumable download of the NSE archive files the quant store is built from.

Per trading day, three published files are kept exactly as NSE served them:

- ``fo``          F&O bhavcopy (UDiFF from 2024-07-08, legacy format before)
- ``participant`` participant-wise open interest (FII / DII / Pro / Client)
- ``mto``         security-wise delivery position
- ``indices``     official open/high/low/close of every NSE index, incl. India VIX

Raw files live under ``<data_cache_dir>/quant/raw/<kind>/<year>/``; a manifest CSV
records each (day, kind) as ``ok`` or ``missing`` (holiday / never published).
Re-running skips what is already done, so an interrupted run just continues.
Published archives never change, so nothing is ever re-downloaded.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import VendorUnavailableError
from tradingagents.dataflows.files import replace_file
from tradingagents.dataflows.vendors.nse.client import NSEDataNotPublishedError
from tradingagents.dataflows.vendors.nse.derivatives import UDIFF_SINCE, legacy_url, udiff_url

logger = logging.getLogger(__name__)

KINDS = ("fo", "participant", "mto", "indices")
MANIFEST_FIELDS = ["day", "kind", "status", "url", "bytes", "fetched_at"]


def participant_oi_url(day: date) -> str:
    return f"/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv"


def mto_url(day: date) -> str:
    return f"/archives/equities/mto/MTO_{day:%d%m%Y}.DAT"


def index_close_url(day: date) -> str:
    return f"/content/indices/ind_close_all_{day:%d%m%Y}.csv"


def candidate_urls(kind: str, day: date) -> list[str]:
    if kind == "fo":
        urls = [udiff_url(day), legacy_url(day)]
        return urls if day >= UDIFF_SINCE else urls[::-1]
    if kind == "participant":
        return [participant_oi_url(day)]
    if kind == "mto":
        return [mto_url(day)]
    if kind == "indices":
        return [index_close_url(day)]
    raise ValueError(f"unknown kind {kind!r}")


def weekdays(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def calendar_days(start: date, end: date) -> Iterable[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


# NSE sometimes trades on a weekend (Budget days 2025-02-01 and 2026-02-01, Diwali Muhurat
# sessions, disaster-recovery drills). A weekend is probed with this one file; the other
# kinds are fetched only if it was published, so a normal weekend costs a single request.
WEEKEND_PROBE = "indices"


def raw_root() -> Path:
    return Path(get_config()["data_cache_dir"]) / "quant" / "raw"


def raw_path(root: Path, kind: str, day: date, url: str) -> Path:
    return root / kind / f"{day:%Y}" / url.rsplit("/", 1)[-1]


@dataclass
class ManifestRow:
    day: date
    kind: str
    status: str   # "ok" | "missing"
    url: str
    bytes: int
    fetched_at: str


def load_manifest(root: Path) -> dict[tuple[date, str], ManifestRow]:
    path = root / "manifest.csv"
    rows: dict[tuple[date, str], ManifestRow] = {}
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            row = ManifestRow(date.fromisoformat(item["day"]), item["kind"], item["status"], item["url"],
                              int(item["bytes"] or 0), item["fetched_at"])
            rows[(row.day, row.kind)] = row  # later lines win (a retried "missing" that became "ok")
    return rows


def _append_manifest(root: Path, row: ManifestRow) -> None:
    path = root / "manifest.csv"
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow({"day": row.day.isoformat(), "kind": row.kind, "status": row.status, "url": row.url,
                         "bytes": row.bytes, "fetched_at": row.fetched_at})


@dataclass
class BackfillStats:
    fetched: int = 0
    missing: int = 0
    skipped: int = 0
    stopped_early: str = ""


def backfill(
    client,
    start: date,
    end: date,
    kinds: Iterable[str] = KINDS,
    root: Path | None = None,
    retry_missing: bool = False,
    progress: Callable[[date, BackfillStats], None] | None = None,
) -> BackfillStats:
    """Fetch every (day, kind) not yet in the manifest, oldest first. Weekdays get every
    kind; weekends only the ``WEEKEND_PROBE`` file, plus the rest if NSE traded that day.

    Stops cleanly (``stopped_early`` set) if NSE becomes unreachable, so a
    later run resumes where this one stopped rather than marking days missing.
    """
    root = root or raw_root()
    root.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(root)
    stats = BackfillStats()
    kinds = tuple(kinds)
    for day in calendar_days(start, end):
        day_kinds = kinds
        if day.weekday() >= 5:
            day_kinds = (WEEKEND_PROBE,) + tuple(k for k in kinds if k != WEEKEND_PROBE)
        for kind in day_kinds:
            if day.weekday() >= 5 and kind != WEEKEND_PROBE:
                probe = manifest.get((day, WEEKEND_PROBE))
                if not probe or probe.status != "ok":
                    break                                # no weekend session
            done = manifest.get((day, kind))
            if done and (done.status == "ok" or not retry_missing):
                stats.skipped += 1
                continue
            row = None
            for url in candidate_urls(kind, day):
                try:
                    fetched = client.get_archive(url)
                except NSEDataNotPublishedError:
                    continue
                except VendorUnavailableError as exc:
                    stats.stopped_early = f"{day} {kind}: {exc}"
                    logger.warning("NSE unavailable, stopping backfill: %s", exc)
                    return stats
                path = raw_path(root, kind, day, url)
                path.parent.mkdir(parents=True, exist_ok=True)
                replace_file(path, lambda tmp, data=fetched.data: Path(tmp).write_bytes(data))
                row = ManifestRow(day, kind, "ok", url, len(fetched.data), _now())
                stats.fetched += 1
                break
            if row is None:
                row = ManifestRow(day, kind, "missing", candidate_urls(kind, day)[0], 0, _now())
                stats.missing += 1
            _append_manifest(root, row)
            manifest[(day, kind)] = row
        if progress:
            progress(day, stats)
    return stats


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
