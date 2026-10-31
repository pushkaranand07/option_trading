"""Gate v2 addendum 3 measurements: allowed features per fold, and baselines on D-1 data (docs/PA_44). No model.

    python scripts/research_gate2_addendum3.py --part folds
    python scripts/research_gate2_addendum3.py --part baselines      # logs each baseline as a trial, once

Folds: a feature exists in a fold if at least 100 signal dates have it for at least 20 U1 stocks (a market feature: a value; an index
feature: one index). Baselines: rule A, the same trades, with direction, weight and the minimum-move filter read one session earlier.
Writes reports/gate/addendum3_*.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import research_gate2_harness as h2  # noqa: E402

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.research import features as fx, gate as g, gate2 as g2, loader, universes as uv  # noqa: E402

OUT = ROOT / "reports" / "gate"
MIN_DATES, MIN_STOCKS = 100, 20
INDEX_ONLY = {"basis_spot_index"}


def run_folds() -> dict:
    spec = fx.read_spec()["features"]
    summ = g.load("base_fo_summary")
    u1, _ = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    all_rows = pd.DataFrame({"signal_date": pd.to_datetime(u1["date"]), "symbol": u1["symbol"].to_numpy(), "kind": u1["kind"].to_numpy()})
    years = all_rows["signal_date"].dt.year
    folds = {f"{a}-{b}": (a, b) for a, b in g.FOLDS}
    tables = {f: loader.load_features(f).assign(signal_date=lambda x: pd.to_datetime(x["signal_date"])) for f in "abcdefgh"}
    rep: dict = {"test": f"at least {MIN_DATES} signal dates with at least {MIN_STOCKS} U1 stocks filled", "dates_with_value": {}, "allowed": {}}
    for fold, (a, b) in folds.items():
        rows = all_rows[(years >= a) & (years <= b)]
        allowed = []
        for t in tables.values():
            names = [c for c in t.columns if c in spec and spec[c]["role"] == "input"]
            if "symbol" in t:
                index_only = [c for c in names if c in INDEX_ONLY]
                stock = rows[rows["kind"] == "stock"][["signal_date", "symbol"]].merge(t[["signal_date", "symbol", *names]], on=["signal_date", "symbol"], how="left")
                counts = stock.groupby("signal_date")[names].count()
                dated = {c: int((counts[c] >= MIN_STOCKS).sum()) for c in names if c not in index_only}
                if index_only:
                    ix = rows[rows["kind"] == "index"][["signal_date", "symbol"]].merge(t[["signal_date", "symbol", *index_only]], on=["signal_date", "symbol"], how="left")
                    dated |= {c: int((ix.groupby("signal_date")[c].count() >= 1).sum()) for c in index_only}
            else:
                days = pd.DatetimeIndex(rows["signal_date"].unique())
                x = t[t["signal_date"].isin(days)]
                dated = {c: int(x[c].notna().sum()) for c in names}
            rep["dates_with_value"].setdefault(fold, {}).update(dated)
            allowed += [c for c, n in dated.items() if n >= MIN_DATES]
        rep["allowed"][fold] = sorted(allowed)
    inputs = sorted(n for n, f in spec.items() if f["role"] == "input")
    rep["folds_of_feature"] = {n: [f for f in folds if n in rep["allowed"][f]] for n in inputs}
    groups: dict[str, list[str]] = {}
    for n, fs in rep["folds_of_feature"].items():
        groups.setdefault(" ".join(fs), []).append(n)
    rep["groups"] = [{"folds": k.split(), "count": len(v), "features": v} for k, v in sorted(groups.items(), key=lambda kv: -len(kv[0]))]
    (OUT / "addendum3_folds.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    for x in rep["groups"]:
        print(len(x["folds"]), x["folds"], x["count"], x["features"][:60])
    return rep


def run_baselines(workers: int) -> dict:
    seen = {t.idea for t in trial_log.load()}
    data = h2.load_rule("A")
    garch = h2.garch_cached(data, workers)
    sessions = pd.to_datetime(pd.Series(data["sessions"]))
    lagged = g2.lag_one_session(data["returns"], data["sessions"], "trade_date")
    lagged_garch = g2.lag_one_session(garch, data["sessions"], "signal")
    rep: dict = {"label": "D-1 data; cost model unverified; slippage ASSUMPTION; known_from of the action list UNVERIFIED", "A": {}}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            t = g.build_trades(data["f"], h, data["sessions"], data["events"])
            t = g.attach_membership(t, data[uni])
            t = g.apply_min_move(t, g.expected_move(lagged, h))
            t = g2.label_action_list(t, data["months"])
            for name in h2.BASELINES:
                x, direction, weight = h2.v1.baseline_rows(name, t, lagged, lagged_garch, h)
                rep["A"].setdefault(f"h{h}", {}).setdefault(uni, {})[name] = h2.measure(x, direction, weight, sessions)
                idea = f"gate_v2_addendum3_baseline_d_minus_1_{name}_h{h}_{uni}"
                if idea not in seen:
                    trial_log.record(trial_log.Trial(idea=idea, params={"h": h, "universe": uni, "timing": "D-1", "gate_sha256": g2.GATE_SHA256}, universe=uni,
                                                     data_start=str(x["entry"].min()), data_end=str(x["exit"].max()), n_trials=1, n_oos_trades=len(x),
                                                     notes="validation read; baseline measurement on D-1 data, not a model; cost model unverified"))
            print(f"h{h} {uni}", flush=True)
    rep["trial_count"] = trial_log.trial_count()
    trial_log.log_event("validation_seen", {"for": "gate item e baselines on D-1 data, addendum 3", "period": "2023-2024", "trials_logged": 50, "gate_sha256": g2.GATE_SHA256})
    (OUT / "addendum3_baselines.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["folds", "baselines"], required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_folds() if args.part == "folds" else run_baselines(args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
