"""Point-in-time audit of the whole store, against NSE's official calendar (docs/PA_31).

    python scripts/research_check_pit.py

For every dataset the research loader serves, reads only trade_date and known_from and reports:
rows, rows without known_from, rows public on or before their own session (both must be 0: FAIL otherwise),
and rows whose known_from is not the next official NSE session after trade_date (reported with the dates;
a later known_from is conservative, an earlier one is a look-ahead and FAILS). Exit code 1 on any FAIL.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds  # noqa: E402
from tradingagents.analytics.backfill import load_manifest, raw_root  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import (  # noqa: E402
    ARCHIVE_HOLES,
    KNOWN_SPECIAL_SESSIONS,
    NSECalendar,
    parse_holiday_master,
)
from tradingagents.dataflows.vendors.nse.client import default_client  # noqa: E402
from tradingagents.research.loader import DERIVED  # noqa: E402


def official_calendar(years: range) -> tuple[NSECalendar, set[date]]:
    """NSE's holiday lists, plus the holidays NSE still published F&O files for (Muhurat sessions: past
    years' lists do not always carry the "*" marker, e.g. 2025-10-21)."""
    client, holidays = default_client(), {}
    for y in years:
        holidays |= parse_holiday_master(client.get_json("/api/holiday-master", {"type": "trading", "year": str(y)},
                                                         ttl=86400).data)
    published = {d for (d, kind), r in load_manifest(raw_root()).items() if kind == "fo" and r.status == "ok"}
    muhurat = {d for d, name in holidays.items() if name.endswith("*")} | (set(holidays) & published)
    return NSECalendar(holidays, special_sessions=set(KNOWN_SPECIAL_SESSIONS), muhurat_days=muhurat), muhurat


def next_session(cal: NSECalendar, day: date) -> date:
    day += timedelta(days=1)
    while not cal.is_trading_day(day):
        day += timedelta(days=1)
    return day


def dates_of(dataset: str) -> pd.DataFrame:
    root = ds.store_root()
    files = (sorted((root / dataset).glob("*.parquet")) if dataset in ds.DATASETS
             else [root.joinpath(*DERIVED[dataset])])
    return pd.concat((pd.read_parquet(f, columns=["trade_date", "known_from"]) for f in files), ignore_index=True)


def main() -> int:
    datasets = ds.DATASETS + tuple(DERIVED)
    frames = {name: dates_of(name) for name in datasets}
    first = min(pd.to_datetime(f["trade_date"]).min() for f in frames.values()).year
    cal, muhurat = official_calendar(range(first, date.today().year + 1))
    print("Holidays with published NSE files, counted as sessions:", ", ".join(map(str, sorted(muhurat))))
    failed = False
    print(f"{'dataset':13s} {'rows':>11s} {'no known_from':>13s} {'known<=trade':>12s} {'off-session':>11s} "
          f"{'later':>7s} {'EARLIER':>7s}  dates where known_from != next official session")
    for name, f in frames.items():
        traded, known = pd.to_datetime(f["trade_date"]).dt.date, pd.to_datetime(f["known_from"]).dt.date
        missing = int(known.isna().sum())
        early = int((known <= traded).sum())
        off = traded[~traded.map({d: cal.is_trading_day(d) for d in set(traded)})]
        expected = traded.map({d: next_session(cal, d) for d in set(traded)})
        # the newest rows' next session may not have happened yet; the store maps them to the next weekday
        settled = expected <= date.today()
        later = settled & (known > expected)
        earlier = settled & (known < expected)
        odd = sorted({(t, k, e) for t, k, e in zip(traded[later | earlier], known[later | earlier],
                                                   expected[later | earlier], strict=True)})
        failed |= bool(missing or early or earlier.any() or len(off))
        print(f"{name:13s} {len(f):>11,} {missing:>13} {early:>12} {len(off):>11} {int(later.sum()):>7} "
              f"{int(earlier.sum()):>7}  " + "; ".join(f"{t} known {k} (official next {e})" for t, k, e in odd[:6]))
        if len(off):
            print(f"{'':13s} rows dated on a non-session: {off.value_counts().sort_index().to_dict()}")
    print("\nArchive holes (sessions whose NSE file is gone):",
          ", ".join(f"{d} {'+'.join(k)}" for d, k in sorted(ARCHIVE_HOLES.items())))
    print("RESULT:", "FAIL" if failed else "PASS (no missing known_from, none on or before its session, none early)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
