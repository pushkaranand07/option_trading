"""Gate v2 reachability: binomial thresholds and the earliest dates for 100 and 150 signal dates (docs/PA_40).

    python scripts/research_gate2_reachability.py --holidays <saved NSE holiday JSON by year>

The null win rate per horizon is measured on development trades (U1, rule A, 1.5x costs). The dates-per-session rate comes
from reports/gate/baselines_v2.json. 2026 holidays come from the saved list; no 2027 list is stored, so every weekday in
2027 counts as a session and the dates are the earliest possible. No request is made. Writes reports/gate/reachability_v2.json.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import research_gate2_harness as h2  # noqa: E402

from tradingagents.research import gate as g, gate2 as g2  # noqa: E402

FIRST = date(2026, 10, 27)
THRESHOLDS = {"1_spec": 0.05, "2_specs": 0.025, "3_specs": 0.05 / 3}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--holidays", type=Path, required=True)
    args = parser.parse_args()
    data = h2.load_rule("A")
    rep: dict = {"null_win_rate": {}, "binomial": {}}
    for h in g.HORIZONS:
        t = h2.trades_for(data, h, "U1")
        t = g.one_open_trade(t[pd.to_datetime(t["entry"]) <= h2.DEV_END])
        c = g._costs(t["kind"], g.GATE_COST_MULTIPLE)
        gr = t["gross"].to_numpy()
        p0 = float((((gr - c) > 0).astype(float) + ((-gr - c) > 0).astype(float)).mean() / 2)
        rep["null_win_rate"][str(h)] = p0
        rep["binomial"][str(h)] = {k: {
            "wins_needed_100": g2.binomial_requirement(p0, a, 100), "wins_needed_150": g2.binomial_requirement(p0, a, 150),
            "dates_needed_at_60pct": g2.binomial_trades_needed(p0, a, 0.60), "dates_needed_at_55pct": g2.binomial_trades_needed(p0, a, 0.55)}
            for k, a in THRESHOLDS.items()}
    saved = json.loads(args.holidays.read_text(encoding="utf-8"))
    hol = {datetime.strptime(r["tradingDate"], "%d-%b-%Y").date() for r in saved["2026"]["FO"]}
    days, d = [], FIRST
    while len(days) < 3000:
        if d.weekday() < 5 and d not in hol:
            days.append(d)
        d += timedelta(days=1)
    base = json.loads((ROOT / "reports" / "gate" / "baselines_v2.json").read_text(encoding="utf-8"))
    rep["earliest"] = {}
    for h in g.HORIZONS:
        rates = [c[p]["all"].get("dates_per_session") for u in base["A"][f"h{h}"].values() for c in u.values() for p in ("development", "validation")]
        r = max(x for x in rates if x)
        rep["earliest"][str(h)] = {"max_dates_per_session": r, "date_100": str(days[math.ceil(100 / r) - 1]), "date_150": str(days[math.ceil(150 / r) - 1])}
    rep["earliest"]["one_date_every_session"] = {"date_100": str(days[99]), "date_150": str(days[149])}
    (ROOT / "reports" / "gate" / "reachability_v2.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
