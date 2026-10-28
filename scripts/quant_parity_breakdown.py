"""Where the stored base's put-call parity flags come from (docs/PA_35). Open periods only; changes nothing.

    python scripts/quant_parity_breakdown.py --years 2015 2016 2017

One row per tested call-put pair (counted on the call). Only pairs where both legs traded are ever tested, so
untraded rows never carry the flag; liquidity is split by the thinner leg's contracts instead. Groups: moneyness
|K / F - 1| (F: the same-expiry future), days to expiry, the thinner leg's contracts, index or stock.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store as bs  # noqa: E402
from tradingagents.research import splits  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", nargs="+", type=int, required=True)
    args = parser.parse_args()
    protected = pd.Timestamp(splits.periods()["final_holdout"].start)
    parts = []
    for y in sorted(args.years):
        c = bs.load(bs.CHAIN, [y])
        c = c[pd.to_datetime(c["known_from"]) < protected]
        key = ["trade_date", "symbol", "expiry", "strike"]
        calls = c[c["parity_tested"] & (c["option_type"] == "CE")]
        puts = c[c["parity_tested"] & (c["option_type"] == "PE")][key + ["contracts"]]
        p = calls.merge(puts, on=key, suffixes=("", "_put"))
        p["thin"] = p[["contracts", "contracts_put"]].min(axis=1)
        p["dte"] = (pd.to_datetime(p["expiry"]) - pd.to_datetime(p["trade_date"])).dt.days
        p["money"] = (p["strike"] / p["ref_price"] - 1).abs()
        p["kind"] = p["instrument"].map({"OPTIDX": "index", "OPTSTK": "stock"})
        parts.append(p[["flag_parity", "thin", "dte", "money", "kind"]])
        untested = c[~c["parity_tested"]]
        print(f"{y}: tested pairs {len(p):,}, flagged {int(p['flag_parity'].sum()):,}; rows never tested "
              f"{len(untested):,} (untraded {int((untested['contracts'] == 0).sum()):,})", flush=True)
    p = pd.concat(parts, ignore_index=True)
    p["moneyness"] = pd.cut(p["money"], [-0.001, 0.025, 0.05, 0.10, 0.25, 10], labels=["<2.5%", "2.5-5%", "5-10%", "10-25%", ">25%"])
    p["days"] = pd.cut(p["dte"], [-1, 7, 30, 70], labels=["0-7", "8-30", "31-70"])
    p["liquidity"] = pd.cut(p["thin"], [0, 9, 99, 999, 1e12], labels=["1-9", "10-99", "100-999", "1000+"])
    total = len(p)
    print(f"\nAll tested pairs: {total:,}, flagged {p['flag_parity'].mean():.1%}")
    for col in ("kind", "moneyness", "days", "liquidity"):
        g = p.groupby(col, observed=True)["flag_parity"].agg(["size", "sum", "mean"])
        g["share_of_flags"] = g["sum"] / p["flag_parity"].sum()
        print(f"\nby {col}:\n" + g.rename(columns={"size": "pairs", "sum": "flagged", "mean": "rate"})
              .to_string(formatters={"rate": "{:.1%}".format, "share_of_flags": "{:.1%}".format}))
    g = p.groupby(["kind", "liquidity"], observed=True)["flag_parity"].agg(["size", "mean"])
    print("\nby kind x liquidity:\n" + g.to_string(formatters={"mean": "{:.1%}".format}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
