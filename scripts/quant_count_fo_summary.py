"""Summarise scripts/quant_count_fo_universe.py's output (docs/PA_33). Reads its files only.

    python scripts/quant_count_fo_summary.py --nse-lists <dir with symbolchange.csv and EQUITY_L.csv>

Every figure for a year with full files is MEASURED. For sample years it is the sample's figure (MEASURED, a lower
bound for counts of names) or an ESTIMATE: mean per file x estimated sessions, where sessions are weekdays minus
NSE's F&O holidays for that year (2010: NSE's API lists none, so the estimate counts every weekday).
Disk for a derived table is an ESTIMATE: rows x the bytes per row the current store's option chain uses.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CURRENT = "m25_d70"                     # the store's filter: +/-25% moneyness, <= 70 days to expiry
OPTIONS = {
    "A. all underlyings, +/-25%, <=70 days (current filter)": (None, "m25_d70"),
    "B. all underlyings, +/-10%, <=35 days": (None, "m10_d35"),
    "C. top 100 by F&O turnover each year, +/-25%, <=70 days": (100, "m25_d70"),
    "D. top 50 by F&O turnover each year, +/-15%, <=35 days": (50, "m15_d35"),
    "unfiltered: every option row, every underlying": (None, "mall_dall"),
}


def est_sessions(year: int, holidays_json: Path | None) -> int:
    days = pd.bdate_range(f"{year}-01-01", f"{year}-12-31")
    hol = set()
    if holidays_json and holidays_json.exists():
        rows = json.loads(holidays_json.read_text(encoding="utf-8")).get(str(year), {}).get("FO", [])
        hol = {datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in rows}
    return int(sum(d.date() not in hol for d in days))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counts", type=Path, default=ROOT / "reports" / "fo_count")
    parser.add_argument("--nse-lists", type=Path, required=True)
    parser.add_argument("--holidays", type=Path, help="NSE holiday-master JSON by year (for session estimates)")
    parser.add_argument("--bytes-per-row", type=float, required=True, help="the current option chain's bytes / rows")
    args = parser.parse_args()

    d = pd.read_parquet(args.counts / "per_symbol_day.parquet")
    files = pd.read_csv(args.counts / "files.csv", parse_dates=["trade_date"])
    exp = pd.read_parquet(args.counts / "expiries.parquet")
    d["year"] = pd.to_datetime(d["trade_date"]).dt.year
    files["year"] = files["trade_date"].dt.year
    exp["year"] = pd.to_datetime(exp["trade_date"]).dt.year
    sample_years = sorted(set(files.loc[files["sample"], "year"]))

    # ---- underlyings per year
    print("\n## Underlyings per year (index / stock; 'other' = e.g. VIX futures)")
    print("year  files  sample  index  stock  other  index_with_options  stock_with_options")
    for y, g in d.groupby("year"):
        nf = int((files["year"] == y).sum())
        k = g.drop_duplicates("symbol").groupby("kind").size()
        ko = g[g["has_options"]].drop_duplicates("symbol").groupby("kind").size()
        print(f"{y}  {nf:5d}  {'yes' if y in sample_years else 'no ':3s}   {k.get('index', 0):5d}  {k.get('stock', 0):5d}  "
              f"{k.get('other', 0):5d}  {ko.get('index', 0):18d}  {ko.get('stock', 0):18d}")
    ever = d.drop_duplicates("symbol").groupby("kind")["symbol"].apply(sorted)
    print("ever, 2010 to today:", {k: len(v) for k, v in ever.items()},
          f"(2010-2014 from {int(files['sample'].sum())} sample files: a lower bound for those years)")
    print("index symbols:", ever.get("index", []))
    print("other symbols:", ever.get("other", []))

    # ---- names that left F&O
    last_day = d["trade_date"].max()
    seen = d.groupby("symbol").agg(kind=("kind", "first"), first=("trade_date", "min"), last=("trade_date", "max"))
    gone = seen[seen["last"] < last_day].sort_values("last")
    sc = pd.read_csv(args.nse_lists / "symbolchange.csv", encoding="latin-1")
    sc.columns = [c.strip() for c in sc.columns]
    renamed = {str(o).strip(): (str(n).strip(), str(e).strip())
               for o, n, e in zip(sc["OLD SYMBOL"], sc["NEW SYMBOL"], sc["EFFECTIVE DATE"], strict=True)}
    eq = pd.read_csv(args.nse_lists / "EQUITY_L.csv", encoding="latin-1")
    listed = set(eq[eq.columns[0]].astype(str).str.strip())
    rows = []
    for s, r in gone.iterrows():
        if r["kind"] != "stock":
            status = "index / other: no longer in F&O"
        elif s in renamed:
            status = f"renamed to {renamed[s][0]} ({renamed[s][1]})"
        elif s in listed:
            status = "still listed on NSE (EQ list); left F&O only"
        else:
            status = "not on NSE's current equity list and no symbol change recorded (delisted / merged: reason UNVERIFIED)"
        rows.append((s, r["kind"], r["first"], r["last"], status))
    gone_df = pd.DataFrame(rows, columns=["symbol", "kind", "first_seen", "last_seen", "status"])
    gone_df.to_csv(args.counts / "left_fo.csv", index=False)
    print(f"\n## Left F&O before {last_day}: {len(gone_df)}")
    print(gone_df.assign(group=gone_df["status"].str.split(" ").str[0:2].str.join(" ")).groupby("group").size().to_string())
    for status in ("renamed", "not on NSE"):
        names = gone_df[gone_df["status"].str.startswith(status)]
        print(f"{status}: {len(names)}: " + ", ".join(f"{s} ({x.split('(')[0].replace('renamed to ', '->').strip()})"
                                                        if status == "renamed" else s
                                                        for s, x in zip(names["symbol"], names["status"], strict=True)))

    # ---- option rows per year and per filter option
    print("\n## Option rows per year (MEASURED for full years; ESTIMATE for sample years)")
    ranks = (d.groupby(["year", "symbol"])["turnover"].sum().groupby(level=0, group_keys=False)
             .rank(ascending=False, method="first"))
    d = d.join(ranks.rename("rank"), on=["year", "symbol"])
    table = []
    for y in sorted(d["year"].unique()):
        g, nf = d[d["year"] == y], int((files["year"] == y).sum())
        sample = y in sample_years
        sessions = est_sessions(y, args.holidays) if sample else nf
        row = {"year": y, "files": nf, "sessions": sessions, "basis": "ESTIMATE" if sample else "MEASURED"}
        for name, (top, col) in OPTIONS.items():
            sel = g if top is None else g[g["rank"] <= top]
            total = float(sel[col].sum())
            row[name] = total / nf * sessions if sample else total
        table.append(row)
    t = pd.DataFrame(table)
    t.to_csv(args.counts / "rows_by_year.csv", index=False)
    show = t.copy()
    for name in OPTIONS:
        show[name] = (show[name] / 1e6).round(2)
    print(show.rename(columns={n: n.split(",")[0] + (" (unf.)" if n.startswith("unf") else "") for n in OPTIONS})
          .to_string(index=False))
    print("(millions of rows)")

    print("\n## Totals and disk (rows MEASURED 2015+, ESTIMATE 2010-2014; disk ESTIMATE at "
          f"{args.bytes_per_row:.1f} bytes/row)")
    for name in OPTIONS:
        meas = t.loc[t["basis"] == "MEASURED", name].sum()
        est = t.loc[t["basis"] == "ESTIMATE", name].sum()
        print(f"  {name}: {meas / 1e6:,.1f}M measured + {est / 1e6:,.1f}M estimated = {(meas + est) / 1e6:,.1f}M rows, "
              f"~{(meas + est) * args.bytes_per_row / 1e9:,.2f} GB")

    # ---- raw disk
    print("\n## Raw F&O files")
    for y, g in files.groupby("year"):
        sample = bool(g["sample"].all())
        size = g["bytes"].sum() if not sample else g["bytes"].mean() * est_sessions(y, args.holidays)
        print(f"  {y}: {'ESTIMATE' if sample else 'MEASURED'} {size / 1e6:,.0f} MB "
              + (f"(mean {g['bytes'].mean() / 1e3:,.0f} KB x {est_sessions(y, args.holidays)} est. sessions)" if sample
                 else f"({len(g)} files)"))

    # ---- lot sizes and expiry calendar
    print("\n## Lot sizes: share of (day, underlying) with a lot (stated in the file, or derivable from open interest)")
    for y, g in d.groupby("year"):
        g = g[g["kind"] != "other"]
        print(f"  {y}: stated {g['lot_stated'].mean():.1%}, derivable {g['lot_derived'].mean():.1%}, "
              f"neither {(~(g['lot_stated'] | g['lot_derived'])).mean():.1%} ({len(g):,} day-underlyings)")
    print("\n## Expiry calendar: distinct option expiry dates listed in the files, per year of expiry")
    exp["expiry_year"] = pd.to_datetime(exp["expiry"]).dt.year
    for grp in ("NIFTY", "BANKNIFTY", "STOCKS"):
        e = exp[(exp["group"] == grp)].drop_duplicates("expiry")
        by = e.groupby("expiry_year").size()
        print(f"  {grp}: " + ", ".join(f"{y}:{n}" for y, n in by.items() if 2010 <= y <= date.today().year))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
