"""Quality checks of the stored base, per the data-foundation standards (docs/PA_34, PA_35).

    python scripts/quant_check_base.py --years 2018 2019 ... 2026

One year at a time. Counts and integrity checks (sessions, duplicates, known_from, lot status, metadata) run on
every year. Checks that read values or statistics (parity and intrinsic rates, > 5 sigma moves, the raw-file
value audit) run only on rows first public before the final holdout (2025-01-01): the protected range is built,
not studied. Prints PASS / FAIL (REPORTED / LISTED where the standard asks for a report); exit code 1 on FAIL.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store as bs, datastore as ds  # noqa: E402
from tradingagents.analytics.backfill import load_manifest, raw_path, raw_root  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import (  # noqa: E402
    ARCHIVE_HOLES,
    KNOWN_SPECIAL_SESSIONS,
    NSECalendar,
    parse_holiday_master,
)
from tradingagents.dataflows.vendors.nse.client import default_client  # noqa: E402
from tradingagents.research import splits  # noqa: E402

CHAIN_KEY = ["trade_date", "symbol", "instrument", "expiry", "strike", "option_type"]
SUMMARY_KEY = ["trade_date", "symbol"]
JUMP_SIGMA, JUMP_WINDOW = 5.0, 60


CIRCULARS = Path(__file__).resolve().parents[1] / "docs" / "data" / "nse_fo_calendar_2010_2014.json"
CIRCULAR_YEARS = range(2010, 2015)      # NSE's holiday API lists none for 2010 and an incomplete 2011


def calendar(years: list[int], published: set[date]) -> NSECalendar:
    """NSE's F&O calendar: from the circulars for 2010-2014, from NSE's holiday API after. Muhurat days count as
    sessions (by the circulars, or for API years when NSE published files on a listed holiday)."""
    client, hol, special, muhurat = default_client(), {}, set(KNOWN_SPECIAL_SESSIONS), set()
    circ = json.loads(CIRCULARS.read_text(encoding="utf-8"))
    for y in range(min(years), max(years) + 2):
        if y in CIRCULAR_YEARS:
            hol |= {date.fromisoformat(d): n for d, n in circ["weekday_holidays"][str(y)]["dates"].items()}
            continue
        api = parse_holiday_master(client.get_json("/api/holiday-master", {"type": "trading", "year": str(y)},
                                                   ttl=86400).data)
        hol |= api
        muhurat |= {d for d, n in api.items() if n.endswith("*")} | (set(api) & published)
    muhurat |= {date.fromisoformat(d) for d in circ["muhurat"]}
    special |= {date.fromisoformat(d) for d in circ["special_sessions"]}
    special |= {d for d, k in ARCHIVE_HOLES.items() if "fo" in k}
    return NSECalendar(hol, special_sessions=special, muhurat_days=muhurat)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    years, results = sorted(args.years), []
    raw, root = raw_root(), ds.store_root()
    ok = {(d, k): r for (d, k), r in load_manifest(raw).items() if r.status == "ok"}
    fo_days = {d for d, k in ok if k == "fo"}
    cal = calendar(years, fo_days)
    protected = splits.periods()["final_holdout"].start
    rng = random.Random(args.seed)
    totals = {"pt": 0, "pf": 0, "it": 0, "if": 0, "rows": 0}
    lots = {"stated": 0, bs.UNVERIFIED: 0, "derived_oi": 0, "none": 0, "other_status": 0}
    summary_all = bs.load(bs.SUMMARY, years)

    def result(name, status, detail):
        results.append(status)
        print(f"[{status}] {name}: {detail}", flush=True)

    def next_session(d: date) -> date:
        d += timedelta(days=1)
        while not cal.is_trading_day(d):
            d += timedelta(days=1)
        return d

    for y in years:
        chain = bs.load(bs.CHAIN, [y])
        summary = summary_all[pd.to_datetime(summary_all["trade_date"]).dt.year == y]
        # 1. sessions vs NSE's holiday lists (archive holes count as documented holes, not gaps)
        weekdays = [d.date() for d in pd.bdate_range(f"{y}-01-01", f"{y}-12-31") if d.date() <= max(fo_days)]
        missing = [d for d in weekdays if cal.is_trading_day(d) and d not in fo_days and d not in ARCHIVE_HOLES]
        base_days = set(summary["trade_date"])
        diff = sorted(base_days ^ {d for d in fo_days if d.year == y})
        holes = sorted(d for d in ARCHIVE_HOLES if d.year == y and "fo" in ARCHIVE_HOLES[d])
        status = "FAIL" if missing or diff or holes else "PASS"
        result(f"{y} sessions vs NSE calendar", status,
               f"{sum(d.year == y for d in fo_days)} F&O files; unexplained missing {missing}; base vs files {diff}"
               + (f"; documented NSE archive holes (unrecoverable, kept FAIL) {holes}" if holes else ""))
        # 2. duplicates
        for name, df, key in ((bs.SUMMARY, summary, SUMMARY_KEY), (bs.CHAIN, chain, CHAIN_KEY)):
            dup = int(df.duplicated(key).sum())
            result(f"{y} {name} duplicate keys", "PASS" if dup == 0 else "FAIL", f"{dup} of {len(df):,}")
        # 3. known_from
        for name, df in ((bs.SUMMARY, summary), (bs.CHAIN, chain)):
            t, k = pd.to_datetime(df["trade_date"]).dt.date, pd.to_datetime(df["known_from"]).dt.date
            exp = t.map({d: next_session(d) for d in set(t)})
            settled = exp <= date.today()
            bad = int(k.isna().sum() + (k <= t).sum() + (settled & (k != exp)).sum())
            result(f"{y} {name} known_from = next official session", "PASS" if bad == 0 else "FAIL",
                   f"{bad} rows wrong")
        # 4. lots: verified only when stated in the file
        for s in ("stated", bs.UNVERIFIED):
            lots[s] += int((summary["lot_status"] == s).sum())
        lots["other_status"] += int((~summary["lot_status"].isin(["stated", bs.UNVERIFIED])).sum())
        for s in ("derived_oi", "none"):
            lots[s] += int((summary["lot_source"] == s).sum())
        wrong = int(((summary["lot_source"] == "stated") != (summary["lot_status"] == "stated")).sum())
        result(f"{y} lot_status stated only where the file states it", "PASS" if wrong == 0 else "FAIL",
               f"stated {int((summary['lot_status'] == 'stated').sum()):,}, UNVERIFIED "
               f"{int((summary['lot_status'] == bs.UNVERIFIED).sum()):,}, inconsistent {wrong}")
        # value / statistics checks: open periods only
        open_rows = pd.to_datetime(chain["known_from"]) < pd.Timestamp(protected)
        c = chain[open_rows]
        totals["rows"] += len(c)
        totals["pt"] += int(c["parity_tested"].sum())
        totals["pf"] += int(c["flag_parity"].sum())
        totals["it"] += int(c["intrinsic_tested"].sum())
        totals["if"] += int(c["flag_below_intrinsic"].sum())
        if len(c):
            s_open = summary[pd.to_datetime(summary["known_from"]) < pd.Timestamp(protected)]
            good = 0
            for name, df, cols in ((bs.SUMMARY, s_open, ["fut_close", "fut_oi", "call_oi", "put_oi"]),
                                   (bs.CHAIN, c, ["close", "settle", "open_interest", "contracts"])):
                good = 0
                for _, r in df.iloc[rng.sample(range(len(df)), 10)].iterrows():
                    rec = ok[(r["trade_date"], "fo")]
                    fo = bs.parse_fo_with_style(raw_path(raw, "fo", r["trade_date"], rec.url).read_bytes(),
                                     rec.url.rsplit("/", 1)[-1])
                    if name == bs.CHAIN:
                        m = fo[(fo["symbol"] == r["symbol"]) & (fo["expiry"] == r["expiry"])
                               & (fo["strike"] == r["strike"]) & (fo["option_type"] == r["option_type"])]
                        same = len(m) == 1 and all(np.isclose(float(m[x].iloc[0]), float(r[x])) for x in cols)
                    else:
                        again = ds.fo_summary(fo, [r["symbol"]]).iloc[0]
                        same = all(np.isclose(float(again[x]), float(r[x]), equal_nan=True) for x in cols)
                    good += bool(same and (fo["trade_date"] == r["trade_date"]).all())
                result(f"{y} {name} 10 random rows vs raw file", "PASS" if good == 10 else "FAIL", f"{good}/10")
        else:
            print(f"[--] {y}: value checks not run (protected range from {protected})", flush=True)
        del chain, c

    if totals["pt"]:
        result("put-call parity (> 1% of F)", "REPORTED",
               f"{totals['pf']:,} of {totals['pt']:,} tested rows flagged ({totals['pf'] / totals['pt']:.1%}), "
               f"open-period rows only; flagged rows kept")
        result("below discounted intrinsic", "REPORTED",
               f"{totals['if']:,} of {totals['it']:,} tested traded rows ({totals['if'] / totals['it']:.2%}); kept")

    # > 5 sigma moves, open periods only
    s = summary_all[pd.to_datetime(summary_all["known_from"]) < pd.Timestamp(protected)].copy()
    if len(s):
        s["ref"] = s["underlying_price"].fillna(s["fut_close"])
        s = s.sort_values(["symbol", "trade_date"])
        s["ret"] = np.log(s["ref"]).groupby(s["symbol"]).diff()
        s["sd"] = s.groupby("symbol")["ret"].transform(lambda r: r.shift(1).rolling(JUMP_WINDOW, min_periods=20).std())
        jumps = s[s["ret"].abs() > JUMP_SIGMA * s["sd"]][["trade_date", "symbol", "kind", "ref", "ret", "sd"]]
        out = root / f"base_jumps_{years[0]}_{years[-1]}.csv"
        jumps.to_csv(out, index=False)
        result("one-day moves > 5 sigma", "LISTED", f"{len(jumps)} on {jumps['symbol'].nunique()} underlyings -> {out}")

    print(f"Lots, all years: stated {lots['stated']:,}; UNVERIFIED {lots[bs.UNVERIFIED]:,} "
          f"(derived from open interest {lots['derived_oi']:,}, no lot {lots['none']:,})")
    meta = json.loads((root / "base_manifest.json").read_text(encoding="utf-8"))
    need = ("rows", "min_date", "max_date", "sha256", "source", "downloaded")
    gaps = [(n, y) for n in bs.DATASETS for y in years
            if not all(meta.get(n, {}).get(str(y), {}).get(k) for k in need)
            or bs.sha256(root / n / f"{y}.parquet") != meta[n][str(y)]["sha256"]]
    result("source, download dates, rows, range, checksum per table", "PASS" if not gaps else "FAIL", f"gaps {gaps}")
    print("\nRESULT:", "FAIL" if "FAIL" in results else "PASS (no FAIL)")
    return 1 if "FAIL" in results else 0


if __name__ == "__main__":
    raise SystemExit(main())
