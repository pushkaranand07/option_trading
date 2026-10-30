"""Skip-rule diagnostics on development data only (2010-2022); nothing is written to the store (docs/PA_40).

    python scripts/quant_action_diagnostics.py

Reports the worst trades, how many trades the missed-event problem touches, and what the price / open-interest detector
would remove beyond NSE's action list, including the sign of those returns.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import datastore as ds  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES  # noqa: E402
from tradingagents.research import gate as g, gate2 as g2, loader, universes as uv  # noqa: E402

END = date(2022, 12, 31)
EXTREME = (-0.40, 0.667)        # the price move of at least a 3:2 bonus or a 2:3 consolidation


def inside(t: pd.DataFrame, ev: pd.DataFrame) -> pd.Series:
    e = ev.rename(columns={"trade_date": "event"})
    m = t[["symbol", "entry", "exit"]].drop_duplicates().merge(e, on="symbol")
    hit = m[(m["event"] > m["entry"]) & (m["event"] <= m["exit"])][["symbol", "entry"]].drop_duplicates().assign(_h=True)
    return t.merge(hit, on=["symbol", "entry"], how="left")["_h"].notna().to_numpy()


def main() -> int:
    f = g.clean_futures(g.load("base_futures", start=date(2010, 1, 1), end=END))
    summ = g.load("base_fo_summary", start=date(2010, 1, 1), end=END)
    actions, months = loader.load_actions(end=END)
    u1, _ = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    sessions = g.session_list(f, [d for d, k in ARCHIVE_HOLES.items() if "fo" in k])
    det, act = g.split_events(f), g2.action_events(actions)
    out: dict = {"last_trade_date": str(f["trade_date"].max()), "months_with_file_2015_2022": len(months)}

    store = ds.store_root()
    m = pd.concat([pd.read_csv(store / n, parse_dates=["trade_date"]) for n in ("base_jumps_matched.csv", "base_jumps_2018_2026_matched.csv")])
    m = m[m["status"].str.startswith("explained")]
    listed = set(zip(m["symbol"], m["trade_date"].dt.date, strict=True))
    d15 = det[pd.to_datetime(det["trade_date"]) >= "2015-01-01"]
    not_on_list = d15[[(s, d) not in listed for s, d in zip(d15["symbol"], d15["trade_date"], strict=True)]]
    # the same flags against the action files themselves, within 3 calendar days, in months with a file
    a = act.rename(columns={"trade_date": "ex"})
    near = not_on_list.merge(a, on="symbol", how="left")
    near["gap"] = (pd.to_datetime(near["trade_date"]) - pd.to_datetime(near["ex"])).dt.days
    has = set(zip(near.loc[near["gap"].between(0, 3), "symbol"], near.loc[near["gap"].between(0, 3), "trade_date"], strict=True))
    unlisted = not_on_list[[(s, d) not in has for s, d in zip(not_on_list["symbol"], not_on_list["trade_date"], strict=True)]]
    out["flags"] = {"all_2010_2022": len(det), "before_2015_no_action_list": len(det) - len(d15), "2015_2022": len(d15),
                    "not_on_large_move_list": len(not_on_list), "of_which_in_development": len(not_on_list),
                    "of_those_with_an_action_in_the_files_within_3_days": len(not_on_list) - len(unlisted),
                    "of_those_with_none": len(unlisted)}

    rows = {}
    for h in g.HORIZONS:
        raw = g.attach_membership(g.build_trades(f, h, sessions), u1)
        raw = raw[pd.to_datetime(raw["exit"]) <= pd.Timestamp(END)].reset_index(drop=True)
        raw = g2.label_action_list(raw, months)
        by_act, by_det = inside(raw, act), inside(raw, det)
        by_flag = inside(raw, not_on_list[["symbol", "trade_date"]])
        a_only = raw[~by_act]
        ext = (a_only["gross"] <= EXTREME[0]) | (a_only["gross"] >= EXTREME[1])
        worst = raw.nsmallest(1, "gross").iloc[0]
        flag_rows = raw[by_flag & ~by_act]
        rows[h] = {"trades": len(raw), "with_action_list": int(raw["has_action_list"].sum()),
                   "removed_by_action_list": int(by_act.sum()), "removed_by_detector": int(by_det.sum()),
                   "left_under_A_but_detector_flags_them": int((by_det & ~by_act).sum()),
                   "extreme_under_A": int(ext.sum()), "extreme_under_A_no_action_list": int((ext & ~a_only["has_action_list"]).sum()),
                   "extreme_under_B": int((ext & ~inside(a_only, det)).sum()),
                   "worst": {k: str(worst[k]) for k in ("symbol", "kind", "expiry", "signal", "entry", "exit", "e_open", "x_price", "gross")},
                   "worst_has_action_list": bool(worst["has_action_list"]),
                   "flagged_not_listed_trades": len(flag_rows), "their_positive_share": float((flag_rows["gross"] > 0).mean()) if len(flag_rows) else None,
                   "their_mean_gross_pct": float(flag_rows["gross"].mean() * 100) if len(flag_rows) else None,
                   "their_median_gross_pct": float(flag_rows["gross"].median() * 100) if len(flag_rows) else None}
    out["by_h"] = rows
    worst = g.attach_membership(g.build_trades(f, 10, sessions, det), u1)
    worst = worst[pd.to_datetime(worst["exit"]) <= pd.Timestamp(END)].nsmallest(5, "gross")
    out["worst_five_h10_under_v1_detector"] = worst[["symbol", "signal", "entry", "exit", "expiry", "e_open", "x_price", "gross"]].astype(str).to_dict("records")
    top = worst.iloc[0]
    c = f[(f["symbol"] == top["symbol"]) & (f["expiry"] == top["expiry"]) & (f["trade_date"] >= top["entry"]) & (f["trade_date"] <= top["exit"])]
    out["worst_path"] = c[["trade_date", "open", "close", "open_interest", "contracts"]].astype(str).to_dict("records")
    out["actions_for_worst"] = actions[actions["symbol"] == top["symbol"]].astype(str).to_dict("records")[-6:]
    (ROOT / "reports" / "gate").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "gate" / "action_diagnostics.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
