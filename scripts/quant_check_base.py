"""Quality checks of the stored base, per the data-foundation standards (docs/PA_34).

    python scripts/quant_check_base.py --years 2015 2016 2017

Prints PASS / FAIL (or REPORTED / LISTED where the standard asks for a report) with the measured numbers, and
writes the price jumps for review to <store>/base_jumps.csv. Exit code 1 on any FAIL.
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

CHAIN_KEY = ["trade_date", "symbol", "instrument", "expiry", "strike", "option_type"]
SUMMARY_KEY = ["trade_date", "symbol"]
JUMP_SIGMA, JUMP_WINDOW = 5.0, 60


def calendar(years: list[int], published: set[date]) -> tuple[NSECalendar, dict[date, str]]:
    client, hol = default_client(), {}
    for y in range(min(years), max(years) + 2):
        hol |= parse_holiday_master(client.get_json("/api/holiday-master", {"type": "trading", "year": str(y)},
                                                    ttl=86400).data)
    muhurat = {d for d, n in hol.items() if n.endswith("*")} | (set(hol) & published)
    return NSECalendar(hol, special_sessions=set(KNOWN_SPECIAL_SESSIONS), muhurat_days=muhurat), hol


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    years, results = sorted(args.years), []
    raw, root = raw_root(), ds.store_root()
    manifest = load_manifest(raw)
    ok = {(d, k): r for (d, k), r in manifest.items() if r.status == "ok"}
    fo_days = {d for d, k in ok if k == "fo"}
    cal, hol = calendar(years, fo_days)
    summary = bs.load(bs.SUMMARY, years)
    chain = bs.load(bs.CHAIN, years)

    def result(name, status, detail):
        results.append(status)
        print(f"[{status}] {name}: {detail}")

    # 1. trading days vs NSE's holiday lists
    for y in years:
        weekdays = [d.date() for d in pd.bdate_range(f"{y}-01-01", f"{y}-12-31")]
        missing = [d for d in weekdays if cal.is_trading_day(d) and d not in fo_days and d not in ARCHIVE_HOLES]
        extra = sorted(set(pd.to_datetime(summary["trade_date"]).dt.date[pd.to_datetime(summary["trade_date"]).dt.year == y])
                       ^ {d for d in fo_days if d.year == y})
        result(f"{y} sessions vs NSE holiday list", "PASS" if not missing and not extra else "FAIL",
               f"{sum(d.year == y for d in fo_days)} F&O files; unexplained missing sessions {missing}; "
               f"days in the base but not in the files (or the reverse) {extra}")

    # 2. duplicates
    for name, df, key in ((bs.SUMMARY, summary, SUMMARY_KEY), (bs.CHAIN, chain, CHAIN_KEY)):
        dup = int(df.duplicated(key).sum())
        result(f"{name} duplicate keys", "PASS" if dup == 0 else "FAIL", f"{dup} of {len(df):,} rows ({', '.join(key)})")

    # 3. option-chain consistency: flagged, never dropped
    pt, pf = int(chain["parity_tested"].sum()), int(chain["flag_parity"].sum())
    it, iflag = int(chain["intrinsic_tested"].sum()), int(chain["flag_below_intrinsic"].sum())
    result("put-call parity (|C-P-e^-rT(F-K)| > 1% of F, same-expiry future as F)", "REPORTED",
           f"{pf:,} of {pt:,} tested rows flagged ({pf / pt:.1%}); {len(chain) - pt:,} rows not testable "
           f"(no traded pair or no same-expiry future); flagged rows kept")
    result("price below discounted intrinsic (no valid implied vol; by > max(0.05, 0.25% of F))", "REPORTED",
           f"{iflag:,} of {it:,} tested traded rows flagged ({iflag / it:.2%}); flagged rows kept")

    # 4. price jumps > 5 sigma (reference price: NSE's underlying, else the near-month future)
    s = summary.copy()
    s["ref"] = s["underlying_price"].fillna(s["fut_close"])
    s = s.sort_values(["symbol", "trade_date"])
    s["ret"] = np.log(s["ref"]).groupby(s["symbol"]).diff()
    s["sd"] = s.groupby("symbol")["ret"].transform(lambda r: r.shift(1).rolling(JUMP_WINDOW, min_periods=20).std())
    jumps = s[(s["ret"].abs() > JUMP_SIGMA * s["sd"])][["trade_date", "symbol", "kind", "ref", "ret", "sd"]]
    jumps.to_csv(root / "base_jumps.csv", index=False)
    result(f"one-day moves > {JUMP_SIGMA:.0f} sigma ({JUMP_WINDOW}-session sigma of earlier days)", "LISTED",
           f"{len(jumps)} moves on {jumps['symbol'].nunique()} underlyings -> {root / 'base_jumps.csv'}; matching to "
           "corporate actions UNVERIFIED (no corporate-action source in the store yet)")

    # 5. point in time
    traded, known = pd.to_datetime(chain["trade_date"]).dt.date, pd.to_datetime(chain["known_from"]).dt.date
    for name, df in ((bs.SUMMARY, summary), (bs.CHAIN, chain)):
        t, k = pd.to_datetime(df["trade_date"]).dt.date, pd.to_datetime(df["known_from"]).dt.date
        nxt = {}
        for d in set(t):
            n = d + timedelta(days=1)
            while not cal.is_trading_day(n):
                n += timedelta(days=1)
            nxt[d] = n
        exp = t.map(nxt)
        bad = int(k.isna().sum() + (k <= t).sum() + (k < exp).sum())
        late = sorted(set(t[k > exp]))
        result(f"{name} known_from (next official session)", "PASS" if bad == 0 else "FAIL",
               f"{bad} missing / not after the session / earlier than the next session; later than it on "
               f"{len(late)} trade dates {late[:5]}")
    del traded, known

    # 6. lot sizes before 2018
    early = pd.to_datetime(summary["trade_date"]) < pd.Timestamp(bs.LOTS_VERIFIED_FROM)
    wrong = int((summary.loc[early, "lot_status"] != bs.UNVERIFIED).sum())
    none = int((summary["lot_source"] == "none").sum())
    result("lot_status UNVERIFIED on every pre-2018 row", "PASS" if wrong == 0 else "FAIL",
           f"{int(early.sum()):,} pre-2018 rows, {wrong} not UNVERIFIED; {none} rows with no lot at all")

    # 7. timestamp / value audit: 10 random rows per dataset against the raw file
    rng = random.Random(args.seed)
    cache = {}
    for name, df, cols in ((bs.SUMMARY, summary, ["fut_close", "fut_oi", "call_oi", "put_oi"]),
                           (bs.CHAIN, chain, ["close", "settle", "open_interest", "contracts"])):
        rows, good = df.iloc[rng.sample(range(len(df)), 10)], 0
        for _, r in rows.iterrows():
            d = r["trade_date"]
            if d not in cache:
                rec = ok[(d, "fo")]
                cache[d] = ds.parse_fo(raw_path(raw, "fo", d, rec.url).read_bytes(), rec.url.rsplit("/", 1)[-1])
            fo = cache[d]
            if name == bs.CHAIN:
                m = fo[(fo["symbol"] == r["symbol"]) & (fo["expiry"] == r["expiry"]) & (fo["strike"] == r["strike"])
                       & (fo["option_type"] == r["option_type"])]
                same = len(m) == 1 and all(np.isclose(float(m[c].iloc[0]), float(r[c])) for c in cols)
            else:
                again = ds.fo_summary(fo, [r["symbol"]]).iloc[0]
                same = all(np.isclose(float(again[c]), float(r[c]), equal_nan=True) for c in cols)
            good += bool(same and (fo["trade_date"] == d).all())
        result(f"{name} 10 random rows vs raw file", "PASS" if good == 10 else "FAIL",
               f"{good}/10 match the raw file ({', '.join(cols)}) and its date")

    # 8. table metadata
    meta = json.loads((root / "base_manifest.json").read_text(encoding="utf-8"))
    need = ("rows", "min_date", "max_date", "sha256", "source", "downloaded")
    gaps = [(n, y) for n in bs.DATASETS for y in years
            if not all(meta.get(n, {}).get(str(y), {}).get(k) for k in need)
            or bs.sha256(root / n / f"{y}.parquet") != meta[n][str(y)]["sha256"]]
    result("source, download dates, rows, date range, checksum per table", "PASS" if not gaps else "FAIL",
           f"missing or mismatched: {gaps}")

    print("\nRESULT:", "FAIL" if "FAIL" in results else "PASS (no FAIL)")
    return 1 if "FAIL" in results else 0


if __name__ == "__main__":
    raise SystemExit(main())
