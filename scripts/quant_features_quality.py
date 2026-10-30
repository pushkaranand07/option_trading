"""Quality checks of feature library v1 on the real store: no target or return-to-target relationship is read (docs/PA_42).

    python scripts/quant_features_quality.py --part truncation
    python scripts/quant_features_quality.py --part checks

Truncation rebuilds features for chosen signal dates from data cut before each date and compares every cell. Checks: known_from
audit, missingness by feature, year and universe, winsor limits (development only), corporate-action, roll and hole handling,
correlation clusters and redundancy. Writes reports/features/*.json and <store>/features_v1/winsor_limits.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import datastore as ds  # noqa: E402
from tradingagents.analytics.backfill import raw_root  # noqa: E402
from tradingagents.research import features as fx, gate as g, loader  # noqa: E402

OUT = ROOT / "reports" / "features"
DEV_END = pd.Timestamp("2022-12-31")
FAMILIES = "abcdefgh"
TRUNCATION_DAYS = (date(2012, 6, 15), date(2015, 3, 16), date(2016, 8, 16), date(2019, 11, 15), date(2021, 3, 31), date(2022, 12, 30), date(2024, 12, 31))
PRICE_FEATURES = ("ret_1", "ret_2", "ret_3", "ret_5", "ret_10", "ret_20", "ret_60", "gap_1", "range_1", "close_loc_1", "oi_chg_1", "oi_chg_5", "oi_z_60", "oi_rel_252", "atm_iv_chg_1")
UNCLIPPED_FAMILIES = "gh"


def store() -> Path:
    return ds.store_root() / "features_v1"


def equal_cells(a: pd.DataFrame, b: pd.DataFrame, keys: list[str]) -> dict:
    x = a.merge(b, on=keys, how="outer", suffixes=("", "__r"), indicator=True)
    only = int((x["_merge"] != "both").sum())
    cells, diff = 0, 0
    worst = None
    both = x[x["_merge"] == "both"]
    for c in a.columns:
        if c in keys or c in ("signal_date", "source_trade_date", "known_from") or f"{c}__r" not in both:
            continue
        u, v = both[c].to_numpy(dtype=float), both[f"{c}__r"].to_numpy(dtype=float)
        same = (np.isnan(u) & np.isnan(v)) | np.isclose(u, v, rtol=1e-9, atol=1e-12)
        cells += len(u)
        bad = int((~same).sum())
        diff += bad
        if bad and worst is None:
            worst = c
    return {"rows_only_on_one_side": only, "cells": cells, "cells_different": diff, "first_different_column": worst}


def run_truncation() -> dict:
    tables = {f: pd.read_parquet(store() / f"{f}.parquet") for f in FAMILIES}
    options = pd.read_parquet(store() / "_options.parquet")
    atm = pd.read_parquet(store() / "_atm.parquet")
    garch = pd.read_parquet(store() / "_garch.parquet")
    full = fx.load_inputs()
    rep: dict = {"days": {}}
    for day in TRUNCATION_DAYS:
        ts = pd.Timestamp(day)
        cut = dict(full)
        for k in ("futures", "participant", "delivery", "index_close", "summary"):
            cut[k] = full[k][pd.to_datetime(full[k]["trade_date"]) < ts]
        cut["events"] = full["events"][pd.to_datetime(full["events"]["ex_date"]) < ts]
        cut["notices"] = full["notices"][full["notices"]["notice"] < ts + pd.Timedelta(hours=15, minutes=30)]
        cut["U1"], cut["U2"] = g.universe_members(cut["summary"], pd.read_csv(fx.g.ROOT / "docs" / "data" / "symbol_map_v1.csv"))
        o = options[pd.to_datetime(options["t"]) < ts]
        a = atm[pd.to_datetime(atm["t"]) < ts]
        gg = garch[pd.to_datetime(garch["t"]) < ts]
        built, _ = fx.build(cut, o, a, gg)
        res = {}
        for fam, t in tables.items():
            left = t[pd.to_datetime(t["signal_date"]) == ts]
            right = built[fam][pd.to_datetime(built[fam]["signal_date"]) == ts]
            keys = ["symbol"] if "symbol" in left else ["signal_date"]
            res[fam] = equal_cells(left, right, keys) | {"rows": len(left)}
        # the option builder alone, on the source session's own chain
        src = cut["summary"]["trade_date"].max()
        chain = loader.load("base_option_chain", start=src, end=day)[fx.CHAIN_COLUMNS]
        chain = loader.european_only(chain[chain["trade_date"] == src])
        o2, _ = fx.options_from_chain(chain)
        o1 = options[pd.to_datetime(options["t"]) == pd.Timestamp(src)]
        cols = [c for c in o2.columns if c not in ("t", "front_expiry")]
        res["option_builder"] = equal_cells(o1[cols], o2[cols], ["symbol"]) | {"rows": len(o1)}
        # GARCH refit on the cut returns, six symbols
        lr = returns_for(cut)
        gres = {"symbols": 0, "cells": 0, "cells_different": 0}
        last = pd.to_datetime(cut["futures"]["trade_date"]).max()
        for sym in ("NIFTY", "BANKNIFTY", "RELIANCE", "SBIN", "INFY", "TATAMOTORS"):
            if sym not in lr:
                continue
            fc = fx.garch_one((sym, lr[sym]))
            stored = garch[(garch["symbol"] == sym) & (pd.to_datetime(garch["t"]) == last)]
            if not len(fc) or not len(stored):
                continue
            mine = fc[pd.to_datetime(fc["t"]) == last]
            if not len(mine):
                continue
            gres["symbols"] += 1
            for h in fx.GARCH_HORIZONS:
                gres["cells"] += 1
                gres["cells_different"] += int(not np.isclose(mine[f"garch_h{h}"].iloc[0], stored[f"garch_h{h}"].iloc[0], rtol=1e-6))
        res["garch_refit"] = gres
        rep["days"][str(day)] = res
        print(day, {k: v.get("cells_different") for k, v in res.items()}, flush=True)
    bad = [(d, f) for d, r in rep["days"].items() for f, v in r.items() if v.get("cells_different") or v.get("rows_only_on_one_side")]
    rep["result"] = "PASS" if not bad else "FAIL"
    rep["failures"] = bad
    (OUT / "truncation.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(rep["result"], bad)
    return rep


def returns_for(inputs: dict) -> pd.DataFrame:
    f0 = inputs["futures"]
    t = pd.to_datetime(f0["trade_date"])
    sessions = pd.DatetimeIndex(sorted(set(t) | {pd.Timestamp(d) for d in inputs["holes"] if pd.Timestamp(d) <= t.max()}))
    f = fx.contract_panel(f0, sessions)
    near = fx.near_rows(f)
    symbols = pd.Index(sorted(near["symbol"].unique()))
    disc, _ = fx.discontinuities(f, near, inputs["events"], sessions, symbols)
    return fx.source_returns(near, disc, sessions, symbols)


def known_from_audit(tables: dict, spec: dict, inputs: dict) -> dict:
    base = pd.DataFrame({"s": pd.to_datetime(inputs["summary"]["trade_date"]), "k": pd.to_datetime(inputs["summary"]["known_from"])}).drop_duplicates("s").set_index("s")["k"]
    out = {}
    for fam, t in tables.items():
        sig, src, kn = pd.to_datetime(t["signal_date"]), pd.to_datetime(t["source_trade_date"]), pd.to_datetime(t["known_from"])
        out[fam] = {"rows": len(t), "known_after_signal": int((kn > sig).sum()), "source_on_or_after_signal": int((src >= sig).sum()),
                    "signal_not_the_base_known_from": int((src.map(base) != sig).sum()), "after_2024": int((sig > pd.Timestamp("2024-12-31")).sum())}
    m = pd.read_csv(raw_root() / "manifest.csv")
    m["day"], m["f"] = pd.to_datetime(m["day"]), pd.to_datetime(m["fetched_at"])
    same = m[(m["status"] == "ok") & (m["f"].dt.normalize() == m["day"])]
    out["raw_publication_evidence"] = {k: {"same_evening_fetches": len(v), "latest": str(v["f"].max()), "earliest": str(v["f"].min())} for k, v in same.groupby("kind")}
    out["raw_publication_history"] = "UNVERIFIED: NSE's historical publication times are not stored; files before 2026-10 were fetched later"
    out["result"] = "PASS" if all(v["known_after_signal"] + v["source_on_or_after_signal"] + v["signal_not_the_base_known_from"] + v["after_2024"] == 0 for k, v in out.items() if k in FAMILIES) else "FAIL"
    return out


def keys_and_membership(tables: dict, inputs: dict) -> pd.DataFrame:
    k = tables["g"][["signal_date", "symbol"]].assign(signal_date=lambda x: pd.to_datetime(x["signal_date"]))
    kinds = inputs["summary"][["symbol", "kind"]].drop_duplicates("symbol")
    k = k.merge(kinds, on="symbol", how="left")
    for u in ("U1", "U2"):
        m = inputs[u]
        k = k.merge(pd.DataFrame({"signal_date": pd.to_datetime(m["date"]), "symbol": m["symbol"].to_numpy(), f"in_{u}": True}).drop_duplicates(), on=["signal_date", "symbol"], how="left")
        k[f"in_{u}"] = k[f"in_{u}"].fillna(False).astype(bool)
    return k


def missingness(tables: dict, spec: dict, keys: pd.DataFrame) -> dict:
    out: dict = {}
    years = keys["signal_date"].dt.year
    for fam, t in tables.items():
        names = [c for c in t.columns if c in spec["features"]]
        if "symbol" in t:
            x = keys.merge(t.assign(signal_date=pd.to_datetime(t["signal_date"]))[["signal_date", "symbol", *names]], on=["signal_date", "symbol"], how="left")
            stocks_only = fam in "eh"
            for u in ("U1", "U2"):
                base = x[f"in_{u}"] & ((x["kind"] == "stock") if stocks_only else True)
                for n in names:
                    miss = x.loc[base, n].isna().groupby(years[base]).mean()
                    out.setdefault(n, {})[u] = {int(y): float(v) for y, v in miss.items()}
        else:
            dates = pd.DatetimeIndex(sorted(keys["signal_date"].unique()))
            x = t.assign(signal_date=pd.to_datetime(t["signal_date"])).set_index("signal_date").reindex(dates)
            for n in names:
                miss = x[n].isna().groupby(dates.year).mean()
                for u in ("U1", "U2"):
                    out.setdefault(n, {})[u] = {int(y): float(v) for y, v in miss.items()}
    return out


def winsor_limits(tables: dict, spec: dict, keys: pd.DataFrame) -> tuple[dict, str]:
    u2 = keys[keys["in_U2"]][["signal_date", "symbol"]]
    limits = {}
    for fam, t in tables.items():
        if fam in UNCLIPPED_FAMILIES:
            continue
        x = t.assign(signal_date=pd.to_datetime(t["signal_date"]))
        x = x[x["signal_date"] <= DEV_END]
        if "symbol" in x:
            x = x.merge(u2, on=["signal_date", "symbol"])
        for n in [c for c in x.columns if c in spec["features"] and spec["features"][c]["role"] == "input" and not c.startswith("nifty_above")]:
            limits[n] = fx.fit_limits(x[n])
    text = json.dumps(limits, indent=1, sort_keys=True)
    (store() / "winsor_limits.json").write_text(text, encoding="utf-8")
    return limits, hashlib.sha256(text.encode()).hexdigest()


def handling(tables: dict, inputs: dict) -> dict:
    a, b = tables["a"], tables["b"]
    t = b[b["disc_flag"] == 1][["symbol", "source_trade_date"]]
    x = t.merge(a, on=["symbol", "source_trade_date"]).merge(b[["symbol", "source_trade_date", "oi_chg_1", "oi_z_60", "oi_chg_5", "oi_rel_252"]], on=["symbol", "source_trade_date"])
    names = [c for c in PRICE_FEATURES if c in x and not c.startswith("atm")]
    non_missing = {c: int(x[c].notna().sum()) for c in names if c in ("ret_1", "gap_1", "range_1", "close_loc_1", "oi_chg_1", "oi_z_60", "oi_rel_252")}
    ev = inputs["events"].assign(source_trade_date=lambda e: pd.to_datetime(e["ex_date"]))[["symbol", "source_trade_date", "subject"]]
    aa = a.assign(source_trade_date=pd.to_datetime(a["source_trade_date"]))
    on_list = ev.merge(aa[["symbol", "source_trade_date", "ret_1", "gap_1", "range_1"]], on=["symbol", "source_trade_date"])
    scheme = on_list[on_list["subject"].str.lower().str.contains("scheme|sheme|arrangement|arangement|amalgam|capital reduction")]
    ade = aa[(aa["symbol"] == "ADANIENT") & (aa["source_trade_date"].between("2015-05-26", "2015-06-08"))][["source_trade_date", "ret_1", "ret_5", "gap_1", "range_1", "rv_20"]]
    bb = b.assign(source_trade_date=pd.to_datetime(b["source_trade_date"]))
    aday = bb[(bb["symbol"] == "ADANIENT") & (bb["source_trade_date"] == "2015-06-03")][["disc_flag", "oi_reset_flag", "oi_chg_1", "oi_z_60"]]
    r = aa["ret_1"].dropna()
    # rolls and holes, from the futures themselves
    f0 = inputs["futures"]
    tt = pd.to_datetime(f0["trade_date"])
    sessions = pd.DatetimeIndex(sorted(set(tt) | {pd.Timestamp(d) for d in inputs["holes"]}))
    f = fx.contract_panel(f0, sessions)
    near = fx.near_rows(f).sort_values(["symbol", "t"])
    near["prev_expiry"] = near.groupby("symbol")["expiry"].shift(1)
    rolled = near[(near["expiry"] != near["prev_expiry"]) & near["prev_expiry"].notna()][["symbol", "t", "close", "p_close"]]
    rr = rolled.merge(aa[["symbol", "source_trade_date", "ret_1"]], left_on=["symbol", "t"], right_on=["symbol", "source_trade_date"])
    same = rr.dropna(subset=["ret_1"])
    diff = np.abs(np.log(same["close"] / same["p_close"]) - same["ret_1"])
    total = f.groupby(["symbol", "t"])["open_interest"].sum().unstack(0).sort_index()
    naive = (total / total.shift(1) - 1).stack().rename("naive").reset_index()
    rc = rolled.merge(naive, on=["symbol", "t"]).merge(bb[["symbol", "source_trade_date", "oi_chg_1"]], left_on=["symbol", "t"], right_on=["symbol", "source_trade_date"])
    holes = [pd.Timestamp(d) for d in inputs["holes"] if pd.Timestamp(d) <= sessions.max()]
    after = [sessions[sessions.get_loc(h) + 1] for h in holes if sessions.get_loc(h) + 1 < len(sessions)]
    tables_rows_on_holes = {f2: int(pd.to_datetime(t2["source_trade_date"]).isin(holes).sum()) for f2, t2 in tables.items()}
    ret_after = int(aa[aa["source_trade_date"].isin(after)]["ret_1"].notna().sum())
    inf = {fam: {c: int(np.isinf(t2[c].to_numpy(dtype=float)).sum()) for c in t2.columns if c not in ("signal_date", "source_trade_date", "known_from", "symbol") and np.isinf(t2[c].to_numpy(dtype=float)).any()} for fam, t2 in tables.items()}
    tr = aa[aa["source_trade_date"].between("2024-06-20", "2024-07-25")].groupby("source_trade_date")["turnover_ratio_20"].median()
    out = {
        "discontinuity_symbol_days": len(t), "non_missing_on_discontinuity_days": non_missing,
        "listed_events_on_stored_symbol_days": len(on_list), "ret_gap_range_values_on_listed_event_days": int(on_list[["ret_1", "gap_1", "range_1"]].notna().sum().sum()),
        "listed_scheme_type_events_on_stored_days": len(scheme), "ret_gap_range_values_on_scheme_days": int(scheme[["ret_1", "gap_1", "range_1"]].notna().sum().sum()),
        "adanient_2015_06_03": aday.astype(float).to_dict("records"), "adanient_path": ade.astype(str).to_dict("records"),
        "largest_abs_ret_1_left": float(r.abs().max()), "abs_ret_1_above_25pct": int((r.abs() > 0.25).sum()), "abs_ret_1_above_35pct": int((r.abs() > 0.35).sum()),
        "abs_ret_1_above_25pct_list": aa.loc[aa["ret_1"].abs() > 0.25, ["symbol", "source_trade_date", "ret_1"]].astype(str).head(40).to_dict("records"),
        "roll_days": len(rolled), "roll_days_with_ret_1": len(same), "ret_1_differs_from_one_contract_return_on_roll_days": int((diff > 1e-9).sum()),
        "roll_days_abs_naive_total_oi_change_median": float(rc["naive"].abs().median()), "roll_days_abs_oi_chg_1_median": float(rc["oi_chg_1"].abs().median()),
        "holes": [str(h.date()) for h in holes], "rows_on_hole_sessions": tables_rows_on_holes, "ret_1_values_on_the_session_after_a_hole": ret_after,
        "infinite_values": {k: v for k, v in inf.items() if v}, "turnover_ratio_20_median_around_2024_07_format_change": {"max": float(tr.max()), "day": str(tr.idxmax().date()), "median": float(tr.median())},
    }
    out["result"] = "PASS" if (not sum(non_missing.values()) and not out["ret_gap_range_values_on_listed_event_days"] and not out["ret_1_differs_from_one_contract_return_on_roll_days"] and not sum(tables_rows_on_holes.values()) and not ret_after and not out["infinite_values"]) else "FAIL"
    return out


def clusters(tables: dict, spec: dict, keys: pd.DataFrame, limits: dict) -> dict:
    members = keys[keys["in_U1"] & (keys["kind"] == "stock") & (keys["signal_date"] <= DEV_END)][["signal_date", "symbol"]]
    x = members
    names: list[str] = []
    for t in tables.values():
        cols = [c for c in t.columns if c in spec["features"] and spec["features"][c]["role"] == "input"]
        tt = t.assign(signal_date=pd.to_datetime(t["signal_date"]))
        on = ["signal_date", "symbol"] if "symbol" in t else ["signal_date"]
        x = x.merge(tt[on + cols], on=on, how="left")
        names += cols
    x = fx.apply_limits(x, limits)
    v = x[names]
    keep = [c for c in names if v[c].notna().sum() >= 1000 and v[c].nunique(dropna=True) > 1]
    rho = v[keep].corr(min_periods=1000)
    dist = (1 - rho.abs()).fillna(1.0).clip(lower=0).to_numpy(copy=True)
    np.fill_diagonal(dist, 0)
    dist = (dist + dist.T) / 2
    labels = fcluster(linkage(squareform(dist, checks=False), "average"), 0.30, "distance")
    groups: dict[int, list[str]] = {}
    for c, label in zip(keep, labels, strict=True):
        groups.setdefault(int(label), []).append(c)
    flagged = []
    for i, a in enumerate(keep):
        for b in keep[i + 1:]:
            if abs(rho.loc[a, b]) > 0.95:
                flagged.append({"a": a, "b": b, "rho": float(rho.loc[a, b])})
    multi = sorted([sorted(g2) for g2 in groups.values() if len(g2) > 1], key=len, reverse=True)
    return {"rows": len(x), "features_in": len(keep), "not_enough_data": [c for c in names if c not in keep], "clusters_total": len(groups), "clusters_with_more_than_one": multi,
            "singletons": sorted(g2[0] for g2 in groups.values() if len(g2) == 1), "above_095": sorted(flagged, key=lambda r: -abs(r["rho"]))}


def run_checks() -> None:
    spec = fx.read_spec()
    tables = {f: pd.read_parquet(store() / f"{f}.parquet") for f in FAMILIES}
    inputs = fx.load_inputs()
    keys = keys_and_membership(tables, inputs)
    rep = {"known_from": known_from_audit(tables, spec, inputs)}
    print("known_from", rep["known_from"]["result"], flush=True)
    rep["handling"] = handling(tables, inputs)
    print("handling", rep["handling"]["result"], flush=True)
    miss = missingness(tables, spec, keys)
    limits, h = winsor_limits(tables, spec, keys)
    rep["winsor"] = {"features": len(limits), "sha256": h, "fitted_on": "signal dates to 2022-12-31, U2 rows"}
    rep["clusters"] = clusters(tables, spec, keys, limits)
    print("clusters", rep["clusters"]["clusters_total"], len(rep["clusters"]["above_095"]), flush=True)
    rep["rows_by_family"] = {f: len(t) for f, t in tables.items()}
    (OUT / "missingness.json").write_text(json.dumps(miss, indent=0), encoding="utf-8")
    (OUT / "checks.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["truncation", "checks"], required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.part == "truncation":
        run_truncation()
    else:
        run_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
