"""Match the stored base's > 5 sigma moves to NSE corporate actions; flag only, no price is adjusted (docs/PA_35).

    python scripts/quant_match_corporate_actions.py --jumps <store>/base_jumps.csv --symbol-changes <symbolchange.csv>

NSE's /api/corporates-corporateActions is fetched one month at a time and kept as raw JSON under
<raw>/corporate_actions/<YYYY-MM>.json (written once, never rewritten). A stock move on day d is explained when the
same symbol (or the symbol it was renamed to or from, per NSE's symbol-change list) has a split or bonus with an
ex-date in [d - 3 days, d]. Other actions in that window (dividends, demergers, rights...) are reported apart and do
not count as explained. Index moves have no corporate actions: they stay UNVERIFIED. Writes <jumps>_matched.csv.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics.backfill import raw_root  # noqa: E402
from tradingagents.dataflows.vendors.nse.client import default_client  # noqa: E402

SPLIT_WORDS = ("splt", "split", "sub-division", "sub division", "subdivision")
BONUS_WORDS = ("bonus",)
WINDOW_DAYS = 3


def month_actions(year: int, month: int, folder: Path, client) -> list[dict]:
    path = folder / f"{year}-{month:02d}.json"
    if not path.exists():
        start = date(year, month, 1)
        end = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
        data = client.get_json("/api/corporates-corporateActions",
                               {"index": "equities", "from_date": f"{start:%d-%m-%Y}", "to_date": f"{end:%d-%m-%Y}"},
                               ttl=0).data
        path.write_text(json.dumps(data), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))


def kind_of(subject: str) -> str:
    s = subject.lower()
    if any(w in s for w in SPLIT_WORDS):
        return "split"
    if any(w in s for w in BONUS_WORDS):
        return "bonus"
    return "other"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--jumps", type=Path, required=True)
    parser.add_argument("--symbol-changes", type=Path, required=True)
    args = parser.parse_args()
    jumps = pd.read_csv(args.jumps, parse_dates=["trade_date"])
    folder = raw_root() / "corporate_actions"
    folder.mkdir(parents=True, exist_ok=True)
    client = default_client()
    months = sorted({(d.year, d.month) for d in jumps["trade_date"]} |
                    {((d - timedelta(days=WINDOW_DAYS)).year, (d - timedelta(days=WINDOW_DAYS)).month)
                     for d in jumps["trade_date"]})
    rows = [r for y, m in months for r in month_actions(y, m, folder, client)]
    ca = pd.DataFrame(rows)
    ca["ex"] = pd.to_datetime(ca["exDate"], format="%d-%b-%Y", errors="coerce")
    ca["symbol"] = ca["symbol"].astype(str).str.strip()
    ca["kind"] = ca["subject"].astype(str).map(kind_of)
    sc = pd.read_csv(args.symbol_changes, encoding="latin-1")
    sc.columns = [c.strip() for c in sc.columns]
    alias: dict[str, set[str]] = {}
    for o, n in zip(sc["OLD SYMBOL"].astype(str).str.strip(), sc["NEW SYMBOL"].astype(str).str.strip(), strict=True):
        alias.setdefault(o, {o}).add(n)
        alias.setdefault(n, {n}).add(o)

    out = []
    for _, j in jumps.iterrows():
        names = alias.get(j["symbol"], {j["symbol"]})
        lo = j["trade_date"] - timedelta(days=WINDOW_DAYS)
        hit = ca[ca["symbol"].isin(names) & (ca["ex"] >= lo) & (ca["ex"] <= j["trade_date"])]
        explained = hit[hit["kind"].isin(["split", "bonus"])]
        status = ("index: no corporate actions; UNVERIFIED" if j["kind"] != "stock"
                  else f"explained: {explained['kind'].iloc[0]}" if len(explained)
                  else "other action in window; UNVERIFIED" if len(hit) else "no action found; UNVERIFIED")
        out.append({**j.to_dict(), "status": status,
                    "actions": "; ".join(f"{e:%Y-%m-%d} {s.strip()}" for e, s in zip(hit["ex"], hit["subject"],
                                                                                       strict=True))})
    res = pd.DataFrame(out)
    dest = args.jumps.with_name(args.jumps.stem + "_matched.csv")
    res.to_csv(dest, index=False)
    print(f"{len(ca):,} corporate actions fetched for {len(months)} months ({datetime.now():%Y-%m-%d})")
    print(res["status"].str.split(";").str[0].value_counts().to_string())
    print(f"-> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
