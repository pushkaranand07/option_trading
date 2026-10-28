"""Reconcile the stored base with the live store for the symbols both hold (docs/PA_35). Changes nothing.

    python scripts/quant_reconcile_base.py --years 2018 ... 2026

For fo_summary vs base_fo_summary and option_chain vs base_option_chain, per year: rows only in one of the two,
and for rows in both, how many differ in each shared column (numbers compared with a relative tolerance of 1e-9,
missing equal to missing). Prints counts only, never values: some years sit in the locked final holdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store as bs, datastore as ds  # noqa: E402

PAIRS = (("fo_summary", bs.SUMMARY, ["trade_date", "symbol"]),
         ("option_chain", bs.CHAIN, ["trade_date", "symbol", "instrument", "expiry", "strike", "option_type"]))


def differ(a: pd.Series, b: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
        x, y = a.to_numpy(float), b.to_numpy(float)
        same = np.isclose(x, y, rtol=1e-9, atol=0, equal_nan=True)
        return pd.Series(~same, index=a.index)
    return (a.astype(str) != b.astype(str)) & ~(a.isna() & b.isna())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    args = parser.parse_args()
    failed = False
    for live_name, base_name, key in PAIRS:
        print(f"\n## {live_name} vs {base_name}")
        for y in sorted(args.years):
            live = ds.load(live_name, start=pd.Timestamp(y, 1, 1).date(), end=pd.Timestamp(y, 12, 31).date())
            if not len(live):
                continue
            symbols = sorted(set(live["symbol"]))
            base = bs.load(base_name, [y], symbols)
            m = live.merge(base, on=key, how="outer", suffixes=("_live", "_base"), indicator=True)
            only_live, only_base = int((m["_merge"] == "left_only").sum()), int((m["_merge"] == "right_only").sum())
            both = m[m["_merge"] == "both"]
            shared = [c for c in live.columns if c not in key and c in base.columns]
            diffs = {c: int(differ(both[f"{c}_live"], both[f"{c}_base"]).sum()) for c in shared}
            bad = {c: n for c, n in diffs.items() if n}
            kf_days = []
            if bad.get("known_from"):
                d = differ(both["known_from_live"], both["known_from_base"])
                kf_days = sorted(set(both.loc[d, "trade_date"]))
            failed |= bool(only_live or only_base or bad)
            print(f"{y}: live {len(live):,} | base (same {len(symbols)} symbols) {len(base):,} | only live {only_live:,} "
                  f"| only base {only_base:,} | rows in both {len(both):,} | columns differing {bad or 'none'}"
                  + (f" | known_from differs on trade dates {kf_days}" if kf_days else ""), flush=True)
    print("\nRESULT:", "MISMATCHES (FAIL until explained)" if failed else "PASS: identical")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
