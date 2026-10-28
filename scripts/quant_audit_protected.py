"""Equality-only audit of the stored base's protected range (docs/PA_36). Changes nothing.

    python scripts/quant_audit_protected.py --years 2025 2026

For each year and table, 10 random rows: the stored values must equal the raw NSE file's (and the file's date).
Prints PASS / FAIL and the number matched; never prints a value, a return or any statistic. The result is written
to the trial log as an ``integrity_check`` event with counts only.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store as bs, datastore as ds, trial_log  # noqa: E402
from tradingagents.analytics.backfill import load_manifest, raw_path, raw_root  # noqa: E402

COLUMNS = {bs.SUMMARY: ["fut_close", "fut_oi", "call_oi", "put_oi", "lot_size"],
           bs.CHAIN: ["close", "settle", "open_interest", "contracts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    raw = raw_root()
    ok = {(d, k): r for (d, k), r in load_manifest(raw).items() if r.status == "ok"}
    rng = random.Random(args.seed)
    results, failed = {}, False
    for y in sorted(args.years):
        for name, cols in COLUMNS.items():
            df = bs.load(name, [y])
            sample, good = df.iloc[rng.sample(range(len(df)), 10)], 0
            for _, r in sample.iterrows():
                rec = ok[(r["trade_date"], "fo")]
                fo = ds.parse_fo(raw_path(raw, "fo", r["trade_date"], rec.url).read_bytes(), rec.url.rsplit("/", 1)[-1])
                if name == bs.CHAIN:
                    m = fo[(fo["symbol"] == r["symbol"]) & (fo["expiry"] == r["expiry"]) & (fo["strike"] == r["strike"])
                           & (fo["option_type"] == r["option_type"])]
                    same = len(m) == 1 and all(np.isclose(float(m[c].iloc[0]), float(r[c])) for c in cols)
                else:
                    again = ds.fo_summary(fo, [r["symbol"]]).iloc[0]
                    same = all(np.isclose(float(again[c]), float(r[c]), equal_nan=True) for c in cols)
                good += bool(same and (fo["trade_date"] == r["trade_date"]).all())
            status = "PASS" if good == 10 else "FAIL"
            failed |= status == "FAIL"
            results[f"{y} {name}"] = {"matched": good, "checked": 10, "rows_in_table": len(df), "result": status}
            print(f"[{status}] {y} {name}: {good}/10 rows equal the raw file", flush=True)
            del df
    detail = {"check": "stored base vs raw NSE file, equality only", "columns": COLUMNS, "seed": args.seed,
              "results": results, "periods": ["final_holdout", "forward_holdout"], "statistics_computed": False}
    json.dumps(detail)
    print("trial-log integrity_check event", trial_log.log_event("integrity_check", detail))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
