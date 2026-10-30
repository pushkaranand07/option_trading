"""Build the symbol continuity map for renamed F&O underlyings from NSE's symbol-change list only (docs/PA_37).

    python scripts/quant_symbol_map.py --symbol-changes <raw>/nse_lists/<date>_symbolchange.csv

A stock that left F&O is a rename candidate only if NSE's list has it as an OLD SYMBOL (no name similarity is used).
A link old -> new is **mapped** when the new symbol trades F&O in the stored base and the two never trade on the same
date; otherwise it stays a separate, labelled series. Links are kept one by one exactly as NSE lists them; a series is
the chain of listed links only (NSE's list carries symbol changes, not mergers or demergers, which are never linked).
At each mapped change date the underlying reference price and the open interest of the old symbol's last session and
the new symbol's first are compared and flagged (|log price ratio| > 0.2, OI ratio outside 0.5-2): flags only, nothing
is adjusted. For changes on or after 2025-01-01 (locked holdout) no price or OI is read: dates and counts only.
Writes docs/data/symbol_map_v1.csv.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import base_store as bs  # noqa: E402
from tradingagents.research import splits  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "docs" / "data" / "symbol_map_v1.csv"
PRICE_FLAG, OI_FLAG = 0.2, (0.5, 2.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol-changes", type=Path, required=True)
    args = parser.parse_args()
    protected = splits.periods()["final_holdout"].start
    s = bs.load(bs.SUMMARY, range(2010, 2027))[["trade_date", "symbol", "kind"]]
    s["trade_date"] = pd.to_datetime(s["trade_date"]).dt.date
    days = s.groupby("symbol")["trade_date"].agg(["min", "max"])
    kind = s.drop_duplicates("symbol").set_index("symbol")["kind"]
    last_day = s["trade_date"].max()
    left = [x for x in days.index if days.loc[x, "max"] < last_day and kind[x] == "stock"]

    sc = pd.read_csv(args.symbol_changes, encoding="latin-1")
    sc.columns = [c.strip() for c in sc.columns]
    sc = sc.assign(old=sc["OLD SYMBOL"].astype(str).str.strip(), new=sc["NEW SYMBOL"].astype(str).str.strip(),
                   eff=pd.to_datetime(sc["EFFECTIVE DATE"].astype(str).str.strip(), format="%d-%b-%Y").dt.date,
                   company=sc["NAME OF THE COMPANY"].astype(str).str.strip())
    candidates = sorted(x for x in left if x in set(sc["old"]))
    rows = []
    for old in candidates:
        for _, r in sc[sc["old"] == old].sort_values("eff").iterrows():
            new = r["new"]
            row = {"old": old, "new": new, "effective_date": r["eff"], "company": r["company"],
                   "source": "NSE symbolchange.csv", "old_first_fo": days.loc[old, "min"],
                   "old_last_fo": days.loc[old, "max"]}
            if new not in days.index:
                rows.append(row | {"status": "unmapped: new symbol never traded F&O in the base"})
                continue
            both = set(s.loc[s["symbol"] == old, "trade_date"]) & set(s.loc[s["symbol"] == new, "trade_date"])
            row |= {"new_first_fo": days.loc[new, "min"], "new_last_fo": days.loc[new, "max"], "overlap_days": len(both)}
            if both:
                rows.append(row | {"status": f"unmapped: old and new both trade on {len(both)} dates"})
                continue
            row["status"] = "mapped"
            first_new = days.loc[new, "min"]
            if first_new >= protected or row["old_last_fo"] >= protected:
                row["flags"] = "not computed (change inside the locked holdout: dates only)"
            else:
                full = bs.load(bs.SUMMARY, sorted({row["old_last_fo"].year, first_new.year}), [old, new])
                full["trade_date"] = pd.to_datetime(full["trade_date"]).dt.date
                a = full[(full["symbol"] == old) & (full["trade_date"] == row["old_last_fo"])].iloc[0]
                b = full[(full["symbol"] == new) & (full["trade_date"] == first_new)].iloc[0]
                pa = a["underlying_price"] if pd.notna(a["underlying_price"]) else a["fut_close"]
                pb = b["underlying_price"] if pd.notna(b["underlying_price"]) else b["fut_close"]
                oa, ob = a["fut_oi"] + a["call_oi"] + a["put_oi"], b["fut_oi"] + b["call_oi"] + b["put_oi"]
                lr = float(np.log(pb / pa)) if pa and pb else float("nan")
                ratio = float(ob / oa) if oa else float("nan")
                flags = []
                if not np.isfinite(lr) or abs(lr) > PRICE_FLAG:
                    flags.append("price")
                if not np.isfinite(ratio) or not OI_FLAG[0] <= ratio <= OI_FLAG[1]:
                    flags.append("open interest")
                row |= {"price_log_ratio": round(lr, 4), "oi_ratio": round(ratio, 4),
                        "gap_sessions": int(((s["trade_date"] > row["old_last_fo"]) & (s["trade_date"] < first_new))
                                            .groupby(s["trade_date"]).any().sum()),
                        "flags": ", ".join(flags) or "none"}
            rows.append(row)
    out = pd.DataFrame(rows)
    # a chain is two listed links meeting at one symbol (e.g. A -> B, B -> C); recorded, never inferred
    out["chain"] = [", ".join(sorted(set(out.loc[out["old"] == n, "new"]) | {o})) if n in set(out["old"]) else ""
                    for o, n in zip(out["old"], out["new"], strict=True)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"{len(candidates)} stocks left F&O and are OLD SYMBOLs in NSE's list; {len(out)} listed links")
    print(out["status"].value_counts().to_string())
    for st in sorted(set(out["status"]) - {"mapped"}):
        print(f"{st}: " + ", ".join(f"{o}->{n}" for o, n in zip(out.loc[out['status'] == st, 'old'],
                                                              out.loc[out['status'] == st, 'new'], strict=True)))
    m = out[out["status"] == "mapped"]
    if "flags" in m:
        print("discontinuity flags among mapped:", m["flags"].value_counts().to_dict())
    print(f"-> {OUT} ({date.today()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
