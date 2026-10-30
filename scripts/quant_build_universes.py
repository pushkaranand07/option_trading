"""Build universe membership U1 / U2 on the stored base (docs/data/universes_v1.json, docs/PA_37).

    python scripts/quant_build_universes.py --equity-list <raw>/nse_lists/<date>_EQUITY_L.csv

Reads base_fo_summary through the research loader (a logged final-holdout unlock: 2026 membership needs 2025
turnover), through 2026-10-26; the forward holdout is not read. 2026 is ranked only inside the sealed function. Writes
<store>/universes/<U>_membership_v1.parquet and <U>_spells_v1.csv, and a trial-log data_build with counts only.
For the open years 2011-2025 it prints the turnover gap between the 100th and 101st names.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds, trial_log  # noqa: E402
from tradingagents.research import loader, splits, universes as uv  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--equity-list", type=Path, required=True)
    args = parser.parse_args()
    rules = uv.addendum()
    end = splits.periods()["final_holdout"].end
    s = loader.load("base_fo_summary", start=date(2010, 1, 1), end=end, unlocks=[loader.Unlock(
        "final_holdout", "batch d: universe membership construction; 2026 ranked sealed, counts only")])
    smap = pd.read_csv(uv.SYMBOL_MAP)
    s = uv.with_series(s, uv.series_ids(smap, s["symbol"]))
    years = range(2011, end.year + 1)
    top = uv.members_by_year(s, years)                      # sealed for every year; values never leave
    out_dir = ds.store_root() / "universes"
    out_dir.mkdir(parents=True, exist_ok=True)
    sessions = sorted(set(s["known_from"]))
    built, counts = {}, {}
    for name in ("U1", "U2"):
        m = uv.membership(s, name, top if name == "U1" else None, through=end)
        sp = uv.spells(m, sessions)
        mp, spp = out_dir / f"{name}_membership_v1.parquet", out_dir / f"{name}_spells_v1.csv"
        ds.write_parquet(m, mp)
        sp.to_csv(spp, index=False)
        built[name] = {"membership": str(mp), "sha256": sha(mp), "rows": len(m), "spells": len(sp)}
        yr = pd.to_datetime(m["date"]).dt.year
        counts[name] = {str(y): {"series": int(g["series"].nunique()),
                                 "stocks": int(g.loc[g["kind"] == "stock", "series"].nunique()),
                                 "indices": int(g.loc[g["kind"] == "index", "series"].nunique())}
                        for y, g in m.groupby(yr)}
        built[name]["frame"] = m

    print("## Members per year (distinct series)\nyear   U1 (stocks + indices)   U2 (stocks + indices)   U1 share of U2")
    for y in sorted(set(counts["U1"]) | set(counts["U2"])):
        a, b = counts["U1"].get(y), counts["U2"][y]
        print(f"{y}   " + (f"{a['series']:4d} ({a['stocks']} + {a['indices']})".ljust(22) if a else "-".ljust(22))
              + f"  {b['series']:4d} ({b['stocks']} + {b['indices']})".ljust(24)
              + (f"  {a['series'] / b['series']:.0%}" if a else ""))
    u1 = built["U1"]["frame"]
    print("\n## U1 indices per year")
    for y, g in u1[u1["kind"] == "index"].groupby(pd.to_datetime(u1.loc[u1["kind"] == "index", "date"]).dt.year):
        names = sorted(set(g["series"]))
        print(f"{y}: {len(names)} {names}")

    print("\n## Open years: turnover of the 100th and 101st stock (inputs before the holdout)")
    for y in years:
        if date(y - 1, 12, 31) >= splits.periods()["final_holdout"].start:
            print(f"{y}: sealed (inputs in the locked holdout); not reported")
            continue
        r = uv.open_ranking(s, y)
        if len(r) > 100:
            a, b = r.iloc[99], r.iloc[100]
            print(f"{y}: #100 {a['series']} Rs {a['turnover'] / 1e7:,.0f} cr | #101 {b['series']} Rs {b['turnover'] / 1e7:,.0f}"
                  f" cr | gap {(a['turnover'] - b['turnover']) / 1e7:,.0f} cr ({a['turnover'] / b['turnover'] - 1:.1%})"
                  f" | eligible {len(r)}")

    # renamed / left-F&O names in each universe (counts and names; no values)
    last = s["trade_date"].max()
    series_last = s.groupby("series")["trade_date"].max()
    symbols_of = s.groupby("series")["symbol"].apply(lambda x: sorted(set(x)))
    eq = pd.read_csv(args.equity_list, encoding="latin-1")
    listed = set(eq[eq.columns[0]].astype(str).str.strip())
    renamed_old = set(smap["old"])
    print("\n## Names that left F&O, or were renamed, inside each universe")
    for name in ("U1", "U2"):
        m = built[name]["frame"]
        stocks = set(m.loc[m["kind"] == "stock", "series"])
        multi = sorted(x for x in stocks if len(symbols_of[x]) > 1)
        gone = sorted(x for x in stocks if series_last[x] < last)
        unmapped_old = sorted(x for x in gone if x in renamed_old and len(symbols_of[x]) == 1)
        not_listed = sorted(x for x in gone if x not in listed and x not in renamed_old)
        print(f"{name}: {len(stocks)} stock series; renamed and joined across symbols {len(multi)} {multi}")
        print(f"   left F&O before {last}: {len(gone)}; of them renamed but unmapped (separate series) "
              f"{len(unmapped_old)}; not on NSE's current equity list, reason UNVERIFIED {len(not_listed)}")
        built[name]["names"] = {"renamed_joined": len(multi), "left_fo": len(gone), "renamed_unmapped": len(unmapped_old),
                                "not_on_equity_list_unverified": len(not_listed)}

    detail = {"addendum": "docs/data/universes_v1.json", "addendum_written_before_ranking": rules["written_before_ranking"],
              "split_sha256": splits.SPLITS_SHA256, "symbol_map_sha256_lf": rules["symbol_map"]["sha256_lf"],
              "through": end, "sealed_rankings": [2026], "open_rankings": "2011-2025",
              "universes": {k: {kk: vv for kk, vv in v.items() if kk != "frame"} for k, v in built.items()},
              "members_by_year": counts, "values_logged": "counts only; no turnover, rank or rank gap for 2026"}
    json.dumps(detail, default=str)
    print("\ntrial-log data_build event", trial_log.log_event("data_build", detail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
