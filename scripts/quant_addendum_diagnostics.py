"""Gate v2 addendum diagnostics from stored data only: no request, no store write (docs/PA_41).

    python scripts/quant_addendum_diagnostics.py --symbol-changes <raw>/nse_lists/<date>_symbolchange.csv

Reports: trades removed only by demergers and consolidations; price-affecting subjects rule A's list leaves out; what a
skip-nothing rule does to rule A's numbers (the bound on using unannounced actions); board-meeting coverage of the listed
actions; and ADANIENT 2015-06 in the raw F&O files and the stored Yahoo prices. Logs the bound as trials.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import datastore as ds, trial_log  # noqa: E402
from tradingagents.analytics.backfill import raw_root  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES  # noqa: E402
from tradingagents.research import gate as g, gate2 as g2, loader, universes as uv  # noqa: E402

DEV_END = pd.Timestamp("2022-12-31")
EXTREME = (-0.40, 0.667)
LEFT_OUT = ("scheme", "sheme", "arrangement", "arangement", "amalgam", "capital reduction", "reduction of capital", "merger")
NOT_LEFT_OUT = ("demerg",)
SYMBOLS_NOTE = "same trade window as rule A: ex-date after entry, up to exit"


def inside(t: pd.DataFrame, ev: pd.DataFrame) -> np.ndarray:
    m = t[["symbol", "entry", "exit"]].drop_duplicates().merge(ev.rename(columns={"trade_date": "event"}), on="symbol")
    hit = m[(m["event"] > m["entry"]) & (m["event"] <= m["exit"])][["symbol", "entry"]].drop_duplicates().assign(_h=True)
    return t.merge(hit, on=["symbol", "entry"], how="left")["_h"].notna().to_numpy()


def describe(x: pd.DataFrame) -> dict:
    if not len(x):
        return {"trades": 0}
    return {"trades": len(x), "positive_share": float((x["gross"] > 0).mean()), "mean_gross_pct": float(x["gross"].mean() * 100),
            "extreme": int(((x["gross"] <= EXTREME[0]) | (x["gross"] >= EXTREME[1])).sum())}


def all_subjects(symbol_changes: Path) -> pd.DataFrame:
    rows = [r for f in sorted((raw_root() / "corporate_actions").glob("*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]
    d = pd.DataFrame(rows)
    out = pd.DataFrame({"symbol": d["symbol"].astype(str).str.strip(), "trade_date": pd.to_datetime(d["exDate"], format="%d-%b-%Y").dt.date,
                        "subject": d["subject"].astype(str).str.strip()})
    sc = pd.read_csv(symbol_changes, encoding="latin-1")
    sc.columns = [c.strip() for c in sc.columns]
    names: dict[str, set[str]] = {}
    for o, n in zip(sc["OLD SYMBOL"].astype(str).str.strip(), sc["NEW SYMBOL"].astype(str).str.strip(), strict=True):
        names.setdefault(o, {o}).add(n)
        names.setdefault(n, {n}).add(o)
    alias = [{**r, "symbol": a} for r in out.to_dict("records") for a in names.get(r["symbol"], ()) if a != r["symbol"]]
    return pd.concat([out, pd.DataFrame(alias)], ignore_index=True).drop_duplicates()


def adanient() -> dict:
    out: dict = {"raw_fo": {}}
    for day in ("29MAY2015", "01JUN2015", "02JUN2015", "03JUN2015", "04JUN2015", "08JUN2015"):
        p = raw_root() / "fo" / "2015" / f"fo{day}bhav.csv.zip"
        if not p.exists():
            out["raw_fo"][day] = "no file"
            continue
        z = zipfile.ZipFile(p)
        d = pd.read_csv(z.open(z.namelist()[0]))
        d.columns = [c.strip() for c in d.columns]
        a = d[d["SYMBOL"].astype(str).str.strip() == "ADANIENT"]
        fut = a[a["INSTRUMENT"].astype(str).str.strip() == "FUTSTK"]
        opt = a[a["INSTRUMENT"].astype(str).str.strip() == "OPTSTK"]
        out["raw_fo"][day] = {"futures": fut[["EXPIRY_DT", "OPEN", "HIGH", "LOW", "CLOSE", "SETTLE_PR", "CONTRACTS", "OPEN_INT", "CHG_IN_OI"]].to_dict("records"),
                              "strike_min": float(opt["STRIKE_PR"].min()), "strike_max": float(opt["STRIKE_PR"].max())}
    px = pd.read_parquet(ds.store_root() / "prices" / "prices.parquet")
    out["prices_columns"] = px.columns.tolist()
    dc = next(c for c in px.columns if "date" in c.lower())
    sc = next((c for c in px.columns if c.lower() in ("symbol", "ticker")), None)
    days = px[dc].astype(str)
    sel = px[(days >= "2015-05-25") & (days <= "2015-06-10")]
    if sc:
        sel = sel[sel[sc].astype(str).str.contains("ADANIENT")]
    out["stored_yahoo"] = sel.astype(str).to_dict("records")
    out["stored_yahoo_first_date_for_symbol"] = str(px[px[sc].astype(str).str.contains("ADANIENT")][dc].min()) if sc else None
    return out


def board_meetings(actions: pd.DataFrame) -> dict:
    rows = []
    folder = raw_root() / "board_meetings"
    for f in sorted(folder.iterdir()):
        x = json.loads(f.read_text(encoding="utf-8"))
        rows += x if isinstance(x, list) else x.get("data", [])
    b = pd.DataFrame(rows)
    stamp = pd.to_datetime(b["bm_timestamp"], format="%d-%b-%Y %H:%M:%S", errors="coerce")
    out = {"files": len(list(folder.iterdir())), "rows": len(b), "first_timestamp": str(stamp.min()), "last_timestamp": str(stamp.max())}
    syms = set(b["bm_symbol"].astype(str))
    a = actions[actions["symbol"].isin(syms) & actions["kind"].isin(["split", "bonus"])].copy()
    a["ex"] = pd.to_datetime(a["ex_date"])
    text = (b["bm_purpose"].astype(str) + " " + b["bm_desc"].astype(str)).str.lower()
    rel = b[text.str.contains("bonus|split|sub-div|subdiv|sub div")].assign(stamp=stamp)
    n_found, gaps = 0, []
    for r in a.itertuples():
        prior = rel[(rel["bm_symbol"] == r.symbol) & (rel["stamp"] < r.ex) & (rel["stamp"] >= r.ex - pd.Timedelta(days=180))]
        if len(prior):
            n_found += 1
            gaps.append((r.ex - prior["stamp"].min()).days)
    out |= {"split_bonus_actions_in_those_symbols": len(a), "with_a_stored_prior_meeting_notice": n_found,
            "days_notice_to_ex_min": min(gaps) if gaps else None, "days_notice_to_ex_median": float(np.median(gaps)) if gaps else None,
            "all_split_bonus_actions": int(actions["kind"].isin(["split", "bonus"]).sum())}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbol-changes", type=Path, required=True)
    args = parser.parse_args()
    start = date(2010, 1, 1)
    f = g.clean_futures(g.load("base_futures", start=start))
    summ = g.load("base_fo_summary", start=start)
    actions, months = loader.load_actions()
    u1, _ = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    sessions = g.session_list(f, [d for d, k in ARCHIVE_HOLES.items() if "fo" in k])
    listed = g2.action_events(actions)
    sb = g2.action_events(actions[actions["kind"].isin(["split", "bonus"])])
    dc = g2.action_events(actions[actions["kind"].isin(["demerger", "consolidation"])])

    subjects = all_subjects(args.symbol_changes)
    low = subjects["subject"].str.lower()
    is_left = low.str.contains("|".join(LEFT_OUT)) & ~low.str.contains("|".join(NOT_LEFT_OUT))
    left = subjects[is_left].merge(listed.assign(_on=True), on=["symbol", "trade_date"], how="left")
    left = left[left["_on"].isna()].drop(columns="_on")
    rep: dict = {"note": SYMBOLS_NOTE, "left_out_rows": len(left), "left_out_subjects": left["subject"].str[:40].value_counts().head(12).to_dict(), "by_h": {}}

    det = g.split_events(f)
    det15 = det[(pd.to_datetime(det["trade_date"]) >= "2015-01-01") & (pd.to_datetime(det["trade_date"]) <= DEV_END)]
    store = ds.store_root()
    m = pd.concat([pd.read_csv(store / n, parse_dates=["trade_date"]) for n in ("base_jumps_matched.csv", "base_jumps_2018_2026_matched.csv")])
    m = m[m["status"].str.startswith("explained")]
    known = set(zip(m["symbol"], m["trade_date"].dt.date, strict=True))
    flags = det15[[(s, d) not in known for s, d in zip(det15["symbol"], det15["trade_date"], strict=True)]]
    near = flags.merge(subjects.rename(columns={"trade_date": "ex"}), on="symbol", how="left")
    near["gap"] = (pd.to_datetime(near["trade_date"]) - pd.to_datetime(near["ex"])).dt.days
    near = near[near["gap"].between(0, 3)]
    keys = near[near["subject"].str.lower().str.contains("|".join(LEFT_OUT))]
    rep["the_115_flags"] = {"flags": len(flags), "any_subject_within_3_days": len(near[["symbol", "trade_date"]].drop_duplicates()),
                            "scheme_type_subject_within_3_days": len(keys[["symbol", "trade_date"]].drop_duplicates()),
                            "top_subjects": near["subject"].str[:30].value_counts().head(8).to_dict()}

    seen = {t.idea for t in trial_log.load()}
    for h in g.HORIZONS:
        raw = g.attach_membership(g.build_trades(f, h, sessions), u1)
        raw = g2.label_action_list(raw, months)
        dev = pd.to_datetime(raw["entry"]) <= DEV_END
        by_all, by_sb, by_dc = inside(raw, listed), inside(raw, sb), inside(raw, dc)
        by_left = inside(raw, left[["symbol", "trade_date"]])
        cost = g._costs(raw["kind"], g.GATE_COST_MULTIPLE)
        row = {"demerger_consolidation_only_dev": describe(raw[dev & by_dc & ~by_sb]),
               "split_bonus_dev": describe(raw[dev & by_sb]),
               "scheme_type_left_in_rule_A_dev": describe(raw[dev & by_left & ~by_all]),
               "extreme_rule_A_dev": describe(raw[dev & ~by_all & ((raw["gross"] <= EXTREME[0]) | (raw["gross"] >= EXTREME[1]))]).get("trades", 0),
               "extreme_rule_A_dev_scheme_type": describe(raw[dev & ~by_all & by_left & ((raw["gross"] <= EXTREME[0]) | (raw["gross"] >= EXTREME[1]))]).get("trades", 0)}
        for name, mask in (("development", dev.to_numpy()), ("validation", ~dev.to_numpy())):
            a = raw[mask & ~by_all]
            ca = cost[mask & ~by_all]
            n_ = raw[mask]
            cn = cost[mask]
            row[f"bound_{name}"] = {"rule_A_trades": len(a), "skip_nothing_trades": len(n_), "skipped_by_list": describe(raw[mask & by_all]),
                                    "always_long_net_1.5x_rule_A_pct": float((a["gross"] - ca).mean() * 100),
                                    "always_long_net_1.5x_skip_nothing_pct": float((n_["gross"] - cn).mean() * 100),
                                    "always_short_net_1.5x_rule_A_pct": float((-a["gross"] - ca).mean() * 100),
                                    "always_short_net_1.5x_skip_nothing_pct": float((-n_["gross"] - cn).mean() * 100)}
        rep["by_h"][str(h)] = row
        idea = f"gate_v2_addendum_skip_nothing_bound_h{h}_U1"
        if idea not in seen:
            trial_log.record(trial_log.Trial(idea=idea, params={"h": h, "universe": "U1", "gate_sha256": g2.GATE_SHA256}, universe="U1",
                                             data_start=str(raw["entry"].min()), data_end=str(raw["exit"].max()), n_trials=1, n_oos_trades=len(raw),
                                             notes="diagnostic bound on rule A's use of unannounced actions, not a model; cost model unverified"))
        print(f"h{h}", flush=True)
    rep["board_meetings"] = board_meetings(actions)
    rep["adanient"] = adanient()
    rep["trial_count"] = trial_log.trial_count()
    (ROOT / "reports" / "gate" / "addendum_diagnostics.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps(rep, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
