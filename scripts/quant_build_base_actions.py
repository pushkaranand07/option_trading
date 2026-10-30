"""Build base_actions from the stored NSE corporate-action files; no download (docs/PA_40).

    python scripts/quant_build_base_actions.py --symbol-changes <raw>/nse_lists/<date>_symbolchange.csv

Keeps actions that change a futures price mechanically: split, bonus, demerger, consolidation. An action is listed under
its symbol and, per NSE's symbol-change list, under the symbol's other names. The files carry no announcement date
(caBroadcastDate is empty on every row), so known_from is not set and its status is UNVERIFIED. Writes
<store>/base_actions/actions.parquet and months.parquet (the months that have a file).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds, trial_log  # noqa: E402
from tradingagents.analytics.backfill import raw_root  # noqa: E402

KINDS = {"split": ("splt", "split", "sub-div", "sub div", "subdiv"), "bonus": ("bonus",), "demerger": ("demerg",),
         "consolidation": ("consolid",)}


def kind_of(subject: str) -> str | None:
    s = subject.lower()
    return next((k for k, words in KINDS.items() if any(w in s for w in words)), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol-changes", type=Path, required=True)
    args = parser.parse_args()
    files = sorted((raw_root() / "corporate_actions").glob("*.json"))
    rows = [r for f in files for r in json.loads(f.read_text(encoding="utf-8"))]
    df = pd.DataFrame(rows)
    announced = int((df["caBroadcastDate"].notna() & ~df["caBroadcastDate"].astype(str).isin(["-", "", "None"])).sum())
    df["kind"] = df["subject"].astype(str).map(kind_of)
    df = df[df["kind"].notna()]
    out = pd.DataFrame({"symbol": df["symbol"].astype(str).str.strip(), "ex_date": pd.to_datetime(df["exDate"], format="%d-%b-%Y").dt.date,
                        "kind": df["kind"], "subject": df["subject"].astype(str).str.strip(), "known_from_status": "UNVERIFIED"})
    sc = pd.read_csv(args.symbol_changes, encoding="latin-1")
    sc.columns = [c.strip() for c in sc.columns]
    names: dict[str, set[str]] = {}
    for o, n in zip(sc["OLD SYMBOL"].astype(str).str.strip(), sc["NEW SYMBOL"].astype(str).str.strip(), strict=True):
        names.setdefault(o, {o}).add(n)
        names.setdefault(n, {n}).add(o)
    alias = [{**r, "symbol": a} for r in out.to_dict("records") for a in names.get(r["symbol"], ()) if a != r["symbol"]]
    out = pd.concat([out, pd.DataFrame(alias)], ignore_index=True).drop_duplicates(["symbol", "ex_date", "kind"])
    folder = ds.store_root() / "base_actions"
    ds.write_parquet(out, folder / "actions.parquet")
    months = pd.DataFrame({"month": [f.stem for f in files]})
    ds.write_parquet(months, folder / "months.parquet")
    counts = out["kind"].value_counts().to_dict()
    event = trial_log.log_event("data_build", {"dataset": "base_actions", "rows": len(out), "kinds": counts, "months": len(files),
                                               "first_month": files[0].stem, "last_month": files[-1].stem,
                                               "rows_with_announcement_date": announced, "known_from": "UNVERIFIED"})
    print(f"{len(out):,} rows {counts}; {len(files)} months {files[0].stem} to {files[-1].stem}; "
          f"rows with an announcement date {announced}; trial-log event {event}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
