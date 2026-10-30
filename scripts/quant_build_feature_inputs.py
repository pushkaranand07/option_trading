"""Build the feature library's other inputs from stored raw files, through 2024; no download (docs/PA_42).

    python scripts/quant_build_feature_inputs.py --symbol-changes <raw>/nse_lists/<date>_symbolchange.csv

Writes <store>/base_participant, base_delivery and base_index (one file per year), and in base_actions: price_events.parquet
(every price-affecting subject of NSE's action files, for the discontinuity flag) and board_notices.parquet (stored board
meeting notices with their own timestamps). known_from is the stored base's, so holes carry no rows and the known_from
is canonical. Raw files dated 2025 or later are not opened; the board-meeting files hold one symbol's whole history, and rows
stamped after 2024 are dropped on reading.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds, trial_log  # noqa: E402
from tradingagents.analytics.backfill import raw_root  # noqa: E402
from tradingagents.research import gate as g  # noqa: E402

LAST = date(2024, 12, 31)
PRICE_SUBJECTS = ("splt", "split", "sub-div", "sub div", "subdiv", "bonus", "demerg", "de-merg", "consolid", "scheme", "sheme",
                  "arrangement", "arangement", "amalgam", "capital reduction", "reduction of capital")


def day_of(name: str) -> date:
    return datetime.strptime(name[-8:], "%d%m%Y").date()


def raw_days(kind: str, prefix: str, suffix: str) -> list[tuple[date, Path]]:
    out = []
    for folder in sorted((raw_root() / kind).iterdir()):
        if not folder.is_dir() or int(folder.name) > LAST.year:
            continue
        out += [(day_of(p.name[len(prefix):-len(suffix)]), p) for p in sorted(folder.glob(f"{prefix}*{suffix}"))]
    return [(d, p) for d, p in out if d <= LAST]


def write_years(name: str, df: pd.DataFrame, known: pd.DataFrame) -> dict:
    """Attach the base's known_from and write one file per year. A session the base does not hold (a hole, or the last day)
    gets no rows."""
    df = df.merge(known, on="trade_date", how="inner")
    years = pd.to_datetime(df["trade_date"]).dt.year
    for y, part in df.groupby(years):
        ds.write_parquet(part.reset_index(drop=True), ds.store_root() / name / f"{y}.parquet")
    return {"rows": len(df), "years": sorted(int(y) for y in years.unique()), "sessions": int(df["trade_date"].nunique())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol-changes", type=Path, required=True)
    args = parser.parse_args()
    summary = g.load("base_fo_summary", start=date(2010, 1, 1))
    known = summary[["trade_date", "known_from"]].drop_duplicates().reset_index(drop=True)
    stocks = set(summary.loc[summary["kind"] == "stock", "symbol"])
    report: dict = {}

    parts, bad = [], []
    for d, p in raw_days("participant", "fao_participant_oi_", ".csv"):
        try:
            parts.append(ds.parse_participant(p.read_bytes(), d))
        except ValueError as exc:
            bad.append(f"{d}: {exc}")
    part = pd.concat(parts, ignore_index=True)
    part = part[part["category"].isin(["Client", "DII", "FII", "Pro"])]
    report["base_participant"] = write_years("base_participant", part, known) | {"unparsed": bad}

    parts = [ds.parse_mto(p.read_bytes()) for _, p in raw_days("mto", "MTO_", ".DAT")]
    deliv = pd.concat(parts, ignore_index=True)
    deliv = deliv[(deliv["series"] == "EQ") & deliv["symbol"].isin(stocks)].drop_duplicates(["trade_date", "symbol"])
    report["base_delivery"] = write_years("base_delivery", deliv, known)

    parts = [ds.parse_index_close(p.read_bytes(), d) for d, p in raw_days("indices", "ind_close_all_", ".csv")]
    index = pd.concat(parts, ignore_index=True).drop_duplicates(["trade_date", "symbol"])
    report["base_index"] = write_years("base_index", index, known)

    rows = [r for f in sorted((raw_root() / "corporate_actions").glob("*.json")) if f.stem <= f"{LAST:%Y-%m}" for r in json.loads(f.read_text(encoding="utf-8"))]
    ca = pd.DataFrame(rows)
    ca = ca[ca["subject"].astype(str).str.lower().str.contains("|".join(PRICE_SUBJECTS))]
    events = pd.DataFrame({"symbol": ca["symbol"].astype(str).str.strip(), "ex_date": pd.to_datetime(ca["exDate"], format="%d-%b-%Y").dt.date,
                           "subject": ca["subject"].astype(str).str.strip()})
    sc = pd.read_csv(args.symbol_changes, encoding="latin-1")
    sc.columns = [c.strip() for c in sc.columns]
    names: dict[str, set[str]] = {}
    for o, n in zip(sc["OLD SYMBOL"].astype(str).str.strip(), sc["NEW SYMBOL"].astype(str).str.strip(), strict=True):
        names.setdefault(o, {o}).add(n)
        names.setdefault(n, {n}).add(o)
    alias = [{**r, "symbol": a} for r in events.to_dict("records") for a in names.get(r["symbol"], ()) if a != r["symbol"]]
    events = pd.concat([events, pd.DataFrame(alias)], ignore_index=True).drop_duplicates(["symbol", "ex_date", "subject"])
    ds.write_parquet(events, ds.store_root() / "base_actions" / "price_events.parquet")
    report["price_events"] = {"rows": len(events)}

    rows = []
    for f in sorted((raw_root() / "board_meetings").glob("*.json")):
        x = json.loads(f.read_text(encoding="utf-8"))
        rows += x if isinstance(x, list) else x.get("data", [])
    b = pd.DataFrame(rows)
    stamp = pd.to_datetime(b["bm_timestamp"], format="%d-%b-%Y %H:%M:%S", errors="coerce")
    notices = pd.DataFrame({"symbol": b["bm_symbol"].astype(str), "meeting": pd.to_datetime(b["bm_date"], format="%d-%b-%Y", errors="coerce"), "notice": stamp,
                            "results": (b["bm_purpose"].astype(str) + " " + b["bm_desc"].astype(str)).str.lower().str.contains("result")})
    notices = notices.dropna(subset=["meeting", "notice"])
    notices = notices[notices["notice"] < pd.Timestamp(LAST) + pd.Timedelta(days=1)].drop_duplicates()
    ds.write_parquet(notices, ds.store_root() / "base_actions" / "board_notices.parquet")
    report["board_notices"] = {"rows": len(notices), "symbols": int(notices["symbol"].nunique()), "first": str(notices["notice"].min())}

    event = trial_log.log_event("data_build", {"dataset": "feature inputs", **report})
    print(json.dumps(report, indent=1, default=str), "trial-log event", event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
