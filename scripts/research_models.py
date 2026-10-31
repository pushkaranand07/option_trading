"""Model suite v1: prepare, fit, evaluate, controls, validation, under the frozen gate (docs/models_v1.json, docs/PA_47).

    python scripts/research_models.py --part prepare       # development rows only; nothing after 2022-12-31 is loaded
    python scripts/research_models.py --part fit --specs a_elastic_logistic b_lightgbm
    python scripts/research_models.py --part evaluate      # development folds; logs the 70 trials
    python scripts/research_models.py --part controls
    python scripts/research_models.py --part truncation
    python scripts/research_models.py --part validate      # only specs that passed development, one read each

Writes reports/models/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES  # noqa: E402
from tradingagents.research import (  # noqa: E402
    features as fx,
    gate as g,
    gate2 as g2,
    loader,
    models as m,
    universes as uv,
)

OUT = ROOT / "reports" / "models"
PRED = OUT / "preds"
DEV_END = date(2022, 12, 31)
LAST = date(2024, 12, 31)
FAMILIES = "abcdefgh"
LEARN = {"a_elastic_logistic": m.fit_sgd_logistic, "a_elastic_linear": m.fit_sgd_linear, "b_lightgbm": m.fit_lgbm_classifier, "d_temporal_cnn": m.fit_tcn, "f_rank": m.fit_lgbm_regressor}
SEEDS_OF = {"a_elastic_logistic": (0,), "a_elastic_linear": (0,)}
GARCH_NEAR = {1: 1, 2: 1, 3: 5, 5: 5, 10: 10}
THREADS = 3


def paths(end: date) -> tuple[Path, str]:
    return OUT / ("dev" if end == DEV_END else "all"), ("dev" if end == DEV_END else "all")


def prepare(end: date = DEV_END) -> None:
    """Rows and features up to ``end``: nothing later is loaded, so the development run cannot read validation."""
    spec = m.read_spec()
    folder, _ = paths(end)
    folder.mkdir(parents=True, exist_ok=True)
    start = date(2010, 1, 1)
    fut = g.clean_futures(g.load("base_futures", start=start, end=end))
    summ = g.load("base_fo_summary", start=start, end=end)
    actions, _months = loader.load_actions(end=end)
    u1, u2 = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    sessions = g.session_list(fut, [d for d, k in ARCHIVE_HOLES.items() if "fo" in k])
    events, returns = g2.prepare(fut, actions, "A")
    lag = g2.lag_one_session(returns, sessions, "trade_date")
    x = None
    for fam in FAMILIES:
        t = loader.load_features(fam, end=end)
        cols = [c for c in t.columns if c in spec["features"]]
        on = ["signal_date", "symbol"] if "symbol" in t else ["signal_date"]
        t = t.assign(signal_date=pd.to_datetime(t["signal_date"]))[on + cols]
        x = t if x is None else (x.merge(t, on=on, how="outer") if "symbol" in t else x.merge(t, on=on, how="left"))
    x = x.dropna(subset=["symbol"]).sort_values(["symbol", "signal_date"]).reset_index(drop=True)
    for c in spec["features"]:
        x[c] = x[c].astype("float32")
    pos = pd.Series(np.arange(len(sessions)), index=pd.to_datetime(pd.Series(sessions)))
    x["signal_pos"] = x["signal_date"].map(pos)
    x = x.dropna(subset=["signal_pos"]).reset_index(drop=True)
    x["signal_pos"] = x["signal_pos"].astype(int)
    x["panel_row"] = np.arange(len(x))
    x.to_parquet(folder / "panel.parquet", index=False)
    r2 = returns.assign(d=pd.to_datetime(returns["trade_date"]))
    wide = r2.pivot(index="d", columns="symbol", values="ret").reindex(pd.to_datetime(pd.Series(sessions)))
    for h in g.HORIZONS:
        t = g.build_trades(fut, h, sessions, events)
        members = {}
        for name, mem in (("in_U1", u1), ("in_U2", u2)):
            k = mem[["date", "symbol"]].rename(columns={"date": "entry"}).drop_duplicates().assign(**{name: True})
            members[name] = k
        t = t.merge(members["in_U1"], on=["symbol", "entry"], how="left").merge(members["in_U2"], on=["symbol", "entry"], how="left")
        t["in_U1"], t["in_U2"] = t["in_U1"].fillna(False).astype(bool), t["in_U2"].fillna(False).astype(bool)
        t = t[t["in_U1"] | t["in_U2"]]
        t = g.apply_min_move(t, g.expected_move(lag, h))
        t["cost"] = g._costs(t["kind"], g.GATE_COST_MULTIPLE)
        t["win_null"] = ((t["gross"] - t["cost"] > 0).astype(float) + (-t["gross"] - t["cost"] > 0).astype(float)) / 2
        fw = np.sqrt((wide ** 2).rolling(h, min_periods=1).mean().shift(-h))
        t3 = fw.stack().rename("t3_vol").rename_axis(["signal", "symbol"]).reset_index()
        t["signal_ts"] = pd.to_datetime(t["signal"])
        t = t.merge(t3.rename(columns={"signal": "signal_ts"}), on=["signal_ts", "symbol"], how="left")
        pm = {d: i for i, d in enumerate(sessions)}
        t["signal_pos"], t["entry_pos"], t["exit_pos"] = t["signal"].map(pm), t["entry"].map(pm), t["exit"].map(pm)
        t["fold"] = g.fold_of(t["entry"])
        t = t.merge(x[["signal_date", "symbol", "panel_row"]], left_on=["signal_ts", "symbol"], right_on=["signal_date", "symbol"], how="left").drop(columns="signal_date")
        t = t.dropna(subset=["panel_row"])
        t["panel_row"] = t["panel_row"].astype(int)
        for c in ("signal", "entry", "exit", "expiry"):
            t[c] = pd.to_datetime(t[c])
        t.sort_values(["signal", "symbol"]).reset_index(drop=True).to_parquet(folder / f"rows_h{h}.parquet", index=False)
        print(f"rows h{h}: {len(t):,}", flush=True)
    (folder / "sessions.json").write_text(json.dumps([str(d) for d in sessions]), encoding="utf-8")
    groups = {}
    a3 = g2.read_addendum_3()["item_g"]["allowed_features_per_fold"]
    for c in spec["features"]:
        groups.setdefault("|".join(k for k, v in a3.items() if c in v), []).append(c)
    (folder / "groups.json").write_text(json.dumps(groups, indent=0), encoding="utf-8")


def load_h(h: int, end: date = DEV_END) -> dict:
    folder, _ = paths(end)
    spec = m.read_spec()
    panel = pd.read_parquet(folder / "panel.parquet")
    rows = pd.read_parquet(folder / f"rows_h{h}.parquet")
    sessions = [date.fromisoformat(s) for s in json.loads((folder / "sessions.json").read_text(encoding="utf-8"))]
    groups = json.loads((folder / "groups.json").read_text(encoding="utf-8"))
    sym = panel["symbol"].astype("category").cat.codes.to_numpy()
    return {"panel": panel, "rows": rows, "sessions": sessions, "groups": groups, "spec": spec, "seq": m.sequence_index(sym, panel["signal_pos"].to_numpy()),
            "allowed": g2.read_addendum_3()["item_g"]["allowed_features_per_fold"]}


def labels(name: str, rows: pd.DataFrame) -> np.ndarray:
    if name == "a_elastic_linear":
        return rows["gross"].to_numpy(dtype=float)
    if name == "f_rank":
        inside = rows["in_U1"].to_numpy() & (rows["kind"].to_numpy() == "stock")
        return rows["gross"].where(inside).groupby(rows["signal"]).rank(pct=True).to_numpy(dtype=float)
    return (rows["gross"].to_numpy() > 0)


def apply_control(rows: pd.DataFrame, panel: pd.DataFrame, control: str | None, h: int) -> tuple[pd.DataFrame, np.ndarray | None]:
    """(rows, training gross override). shuffled and time_shift change only what the model learns; stale changes what it sees."""
    if control is None:
        return rows, None
    if control == "shuffled":
        return rows, np.random.default_rng(99).permutation(rows["gross"].to_numpy())
    if control == "time_shift":
        later = rows[["symbol", "signal_pos", "gross"]].assign(signal_pos=lambda t: t["signal_pos"] - 2 * h).rename(columns={"gross": "_g"})
        y = rows.merge(later, on=["symbol", "signal_pos"], how="left")["_g"].fillna(0.0).to_numpy()
        return rows, y
    if control == "stale":
        key = panel[["symbol", "signal_pos", "panel_row"]].assign(signal_pos=lambda t: t["signal_pos"] + h).rename(columns={"panel_row": "_old"})
        x = rows.merge(key, on=["symbol", "signal_pos"], how="left")
        return x[x["_old"].notna()].assign(panel_row=lambda t: t["_old"].astype(int)).drop(columns="_old").reset_index(drop=True), None
    raise ValueError(control)


def frames(rows: pd.DataFrame, panel: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    extra = [c for c in columns if c in panel]
    out = panel[extra].iloc[rows["panel_row"].to_numpy()].reset_index(drop=True)
    return pd.concat([rows.reset_index(drop=True), out], axis=1)


def fit_one(args: tuple) -> dict:
    """One spec, horizon and fold. Writes holdout and test predictions; returns the chosen grid point."""
    name, h, fold, control, end = args
    d = load_h(h, end)
    rows, panel, sessions = d["rows"], d["panel"], d["sessions"]
    rows, y_override = apply_control(rows, panel, control, h)
    spec = d["spec"]["specs"][name]
    columns = m.allowed_columns(d["spec"]["features"], fold, d["allowed"])
    entry, exit_ = rows["entry_pos"].to_numpy(), rows["exit_pos"].to_numpy()
    mask = m.fit_mask(entry, exit_, fold, h, sessions) & rows["in_U1"].to_numpy()
    if name == "f_rank":
        mask &= rows["kind"].to_numpy() == "stock"
    tr = np.flatnonzero(mask)
    te = np.flatnonzero(rows["fold"].to_numpy() == fold)
    if len(tr) < 1000 or not len(te):
        return {"spec": name, "h": h, "fold": fold, "skipped": True}
    base = rows if y_override is None else rows.assign(gross=y_override)
    y = labels(name, base)
    fit_rows = rows.iloc[tr]
    fr = frames(fit_rows, panel, columns)
    prep_full = m.Prep(fr, columns, d["groups"])
    inner, hold = m.inner_split(fit_rows["signal_pos"].to_numpy(), fit_rows["exit_pos"].to_numpy(), h)
    learn = LEARN[name]
    seeds = (11,) if control else (0,) if name.startswith("a_") else tuple(d["spec"]["protocol"]["seeds"])
    extra = {"panel": {"frame": panel, "seq": d["seq"]}, "threads": THREADS, "monotone": spec.get("monotone")}
    grid = [dict(zip(spec["grid"], v, strict=True)) for v in _product(spec["grid"])]
    if control:
        grid = grid[:1]
    inner_fr, hold_fr = fr[inner], fr[hold]
    prep_inner = m.Prep(inner_fr, columns, d["groups"])
    ytr = y[tr]
    scored = []
    for params in grid:
        predict = learn(inner_fr, ytr[inner], prep_inner, params, seeds[0], **extra)
        p = predict(hold_fr)
        scored.append((_loss(name, p, ytr[hold]), json.dumps(params), p))
    best = min(scored, key=lambda s: s[0])
    params = json.loads(best[1])
    hold_p = best[2]
    test_fr = frames(rows.iloc[te], panel, columns)
    seed_preds = {s: learn(fr, ytr, prep_full, params, s, **extra)(test_fr) for s in seeds}
    tag = f"{name}_h{h}_f{fold}" + (f"_{control}" if control else "") + ("" if end == DEV_END else "_val")
    PRED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"row": te, **{f"p_{s}": v for s, v in seed_preds.items()}}).to_parquet(PRED / f"{tag}_test.parquet", index=False)
    pd.DataFrame({"row": tr[hold], "p": hold_p, "y": ytr[hold].astype(float)}).to_parquet(PRED / f"{tag}_hold.parquet", index=False)
    print(tag, params, flush=True)
    return {"spec": name, "h": h, "fold": fold, "control": control, "params": params, "inner_loss": best[0], "train_rows": len(tr), "columns": len(columns)}


def _product(grid: dict) -> list[tuple]:
    from itertools import product
    return list(product(*grid.values()))


def _loss(name: str, p: np.ndarray, y: np.ndarray) -> float:
    if name in ("a_elastic_linear", "f_rank"):
        return float(np.mean((p - y) ** 2))
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(q) + (1 - y) * np.log(1 - q)))


def run_fit(names: list[str], workers: int, control: str | None = None, horizons=g.HORIZONS, folds=m.DEV_FOLDS, end: date = DEV_END) -> None:
    jobs = [(n, h, f, control, end) for n in names for h in horizons for f in folds]
    t0 = time.monotonic()
    with ProcessPoolExecutor(workers) as pool:
        res = list(pool.map(fit_one, jobs))
    OUT.mkdir(parents=True, exist_ok=True)
    label = "_".join(n[:1] for n in names) + (f"_{control}" if control else "") + ("" if end == DEV_END else "_val")
    (OUT / f"fit_{label}.json").write_text(json.dumps(res, indent=0), encoding="utf-8")
    print(f"fit {names} {control or ''}: {len(jobs)} jobs, {time.monotonic() - t0:.0f}s", flush=True)


# ---------------------------------------------------------------- evaluation

def predictions(name: str, h: int, folds, control: str | None, rows: pd.DataFrame, spec: dict, suffix: str = "") -> dict | None:
    """Per fold: holdout and test scores, calibrated where the spec calibrates."""
    if name == "e_ensemble":
        parts = [predictions(n, h, folds, control, rows, spec, suffix) for n in spec["specs"]["e_ensemble"]["weights"]]
        if any(p is None for p in parts):
            return None
        out = {}
        for f in folds:
            te = pd.DataFrame({"row": parts[0][f]["test_row"], "a": parts[0][f]["test"]}).merge(pd.DataFrame({"row": parts[1][f]["test_row"], "b": parts[1][f]["test"]}), on="row").merge(pd.DataFrame({"row": parts[2][f]["test_row"], "c": parts[2][f]["test"]}), on="row")
            ho = pd.DataFrame({"row": parts[0][f]["hold_row"], "a": parts[0][f]["hold"]}).merge(pd.DataFrame({"row": parts[1][f]["hold_row"], "b": parts[1][f]["hold"]}), on="row").merge(pd.DataFrame({"row": parts[2][f]["hold_row"], "c": parts[2][f]["hold"]}), on="row")
            out[f] = {"test_row": te["row"].to_numpy(), "test": te[["a", "b", "c"]].mean(axis=1).to_numpy(), "hold_row": ho["row"].to_numpy(), "hold": ho[["a", "b", "c"]].mean(axis=1).to_numpy(), "seeds": {}}
        return out
    out = {}
    for f in folds:
        tag = f"{name}_h{h}_f{f}" + (f"_{control}" if control else "") + suffix
        tp, hp = PRED / f"{tag}_test.parquet", PRED / f"{tag}_hold.parquet"
        if not tp.exists():
            out[f] = None
            continue
        t, ho = pd.read_parquet(tp), pd.read_parquet(hp)
        seeds = [c for c in t.columns if c.startswith("p_")]
        mean = t[seeds].mean(axis=1).to_numpy()
        if name in ("a_elastic_linear", "f_rank"):
            out[f] = {"test_row": t["row"].to_numpy(), "test": mean, "hold_row": ho["row"].to_numpy(), "hold": ho["p"].to_numpy(), "seeds": {c: t[c].to_numpy() for c in seeds}}
        else:
            cal = m.platt(ho["p"].to_numpy(), ho["y"].to_numpy())
            out[f] = {"test_row": t["row"].to_numpy(), "test": cal(mean), "hold_row": ho["row"].to_numpy(), "hold": cal(ho["p"].to_numpy()), "seeds": {c: cal(t[c].to_numpy()) for c in seeds}}
    if all(v is None for v in out.values()):
        return None
    return {k: v for k, v in out.items() if v is not None}


def direction(name: str, frame: pd.DataFrame, score: np.ndarray, setting: float) -> np.ndarray:
    if name == "a_elastic_linear":
        return m.act_magnitude(score, frame["cost"].to_numpy(), setting)
    if name == "f_rank":
        return m.act_rank(frame, score, setting, frame["kind"].to_numpy() == "stock")
    return m.act_probability(score, setting)


def settings_of(name: str, spec: dict) -> list[float]:
    s = spec["specs"][name]
    return s.get("band") or s.get("band_cost_multiples") or s.get("bucket")


def choose_setting(name: str, preds: dict, rows: pd.DataFrame, spec: dict) -> float | None:
    by_fold = []
    for p in preds.values():
        hold = rows.iloc[p["hold_row"]]
        scores = {}
        for s in settings_of(name, spec):
            t = m.take_trades(hold, direction(name, hold, p["hold"], s))
            if len(t):
                scores[s] = {"net": float(t["net"].mean()), "dates": int(t["signal"].nunique())}
        by_fold.append(scores)
    return m.best_setting(by_fold)


def universe_trades(name: str, pool: pd.DataFrame, score: np.ndarray, setting: float, flag: str) -> pd.DataFrame:
    keep = pool[flag].to_numpy()
    return m.take_trades(pool[keep], direction(name, pool[keep], score[keep], setting))


def pooled(preds: dict, rows: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    rid = np.concatenate([p["test_row"] for p in preds.values()])
    score = np.concatenate([p["test"] for p in preds.values()])
    return rows.iloc[rid].reset_index(drop=True), score


def evaluate_cell(name: str, h: int, spec: dict, gate: dict, rows: pd.DataFrame, control: str | None = None, baselines: dict | None = None) -> dict:
    x, block = gate["gate"]["g"]["x_h_percent"][str(h)] / 100, gate["gate"]["d"]["block_dates_by_h"][str(h)]
    preds = predictions(name, h, m.DEV_FOLDS, control, rows, spec)
    if not preds:
        return {"spec": name, "h": h, "status": "no predictions", "pass": False}
    setting = choose_setting(name, preds, rows, spec)
    if setting is None:
        return {"spec": name, "h": h, "status": "no setting reached 50 dates on any inner holdout", "pass": False}
    pool, score = pooled(preds, rows)
    u1, u2 = universe_trades(name, pool, score, setting, "in_U1"), universe_trades(name, pool, score, setting, "in_U2")
    u2_net = float(u2["net"].mean()) if len(u2) else float("nan")
    items = m.development_items(u1, u2_net, h, x, block, np.random.default_rng(1000 + h), baselines=baselines)
    out = {"spec": name, "h": h, "label": g2.horizon_label(h), "setting": setting, "items": items, "pass": items["pass"], "control": control}
    if not control and len(u1):
        days = (u1["entry"].max() - u1["entry"].min()).days / 7
        by_year = u1.groupby(u1["entry"].dt.year)["net"].agg(["mean", "count"])
        months = loader.load_actions(end=DEV_END)[1]
        listed = g2.label_action_list(u1, months)
        for label, sub in (("with_action_list", listed[listed["has_action_list"]]), ("no_action_list", listed[~listed["has_action_list"]])):
            out[label] = {"trades": len(sub), "dates": int(sub["signal"].nunique()), "expectancy_pct": float(sub["net"].mean() * 100) if len(sub) else None}
        n15 = u1["net"].to_numpy(dtype=float)
        out["median_pct"], out["winsorized_pct"] = float(np.median(n15) * 100), g2.winsorized_mean(n15) * 100
        only = pool.assign(_only=pool["in_U2"].to_numpy() & ~pool["in_U1"].to_numpy())
        ou = universe_trades(name, only, score, setting, "_only")
        out["u2_minus_u1"] = {"trades": len(ou), "expectancy_pct": float(ou["net"].mean() * 100) if len(ou) else None}
        seed_means = {}
        for c in next(iter(preds.values()))["seeds"]:
            sc = np.concatenate([p["seeds"][c] for p in preds.values()])
            t = universe_trades(name, pool, sc, setting, "in_U1")
            seed_means[c] = float(t["net"].mean() * 100) if len(t) else float("nan")
        vals = [v for v in seed_means.values() if np.isfinite(v)]
        out |= {"dates_per_week": u1["signal"].nunique() / days if days else None, "drawdown_pct": m.drawdown(u1["net"], u1["signal"]), "trades": len(u1), "trades_u2": len(u2),
                "by_year_pct": {int(y): float(r["mean"] * 100) for y, r in by_year.iterrows()}, "seed_expectancy_pct": seed_means, "seed_sign_flips": bool(vals and min(vals) < 0 < max(vals))}
        if name not in ("a_elastic_linear", "f_rank"):
            y = (pool["gross"].to_numpy() > 0).astype(float)
            mask = pool["in_U1"].to_numpy()
            out["brier"] = float(np.mean((score[mask] - y[mask]) ** 2))
            bins = pd.cut(score[mask], [0, 0.4, 0.45, 0.48, 0.5, 0.52, 0.55, 0.6, 1.0])
            r = pd.DataFrame({"b": bins, "p": score[mask], "y": y[mask]}).groupby("b", observed=True).agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
            out["reliability"] = [{"bin": str(i), "predicted": float(v["p"]), "observed": float(v["y"]), "rows": int(v["n"])} for i, v in r.iterrows()]
        panel = pd.read_parquet(paths(DEV_END)[0] / "panel.parquet", columns=["signal_date", "symbol", "vix"])
        vx = panel.dropna(subset=["vix"]).drop_duplicates("signal_date")
        cuts = np.nanpercentile(vx["vix"], [33.33, 66.67])
        t = u1.merge(vx[["signal_date", "vix"]], left_on="signal", right_on="signal_date", how="left")
        t["tercile"] = np.where(t["vix"].isna(), "no VIX", np.where(t["vix"] <= cuts[0], "low", np.where(t["vix"] <= cuts[1], "middle", "high")))
        out["by_vix_tercile_pct"] = {k: float(v) * 100 for k, v in t.groupby("tercile")["net"].mean().items()}
    return out


def dev_baselines(h: int, uni: str, rows: pd.DataFrame) -> dict:
    """Each baseline's 20 schedules on the same development test-fold rows, D-1 timing. Report-only on development."""
    sessions = [date.fromisoformat(s) for s in json.loads((paths(DEV_END)[0] / "sessions.json").read_text(encoding="utf-8"))]
    pos = {pd.Timestamp(d): i for i, d in enumerate(sessions)}
    pool = rows[(rows["fold"] >= 0) & rows[f"in_{uni}"]].copy()
    panel = pd.read_parquet(paths(DEV_END)[0] / "panel.parquet", columns=["panel_row", "ret_1", "ret_5", f"garch_h{GARCH_NEAR[h]}"])
    x = pool.merge(panel, on="panel_row", how="left")
    out: dict = {}
    for name in ("always_long", "always_short", "prev_day", "momentum_5d", "garch_risk_scaled"):
        if name == "always_long":
            d, w = np.ones(len(x)), np.ones(len(x))
        elif name == "always_short":
            d, w = -np.ones(len(x)), np.ones(len(x))
        elif name == "prev_day":
            d, w = np.sign(x["ret_1"].fillna(0).to_numpy()), np.ones(len(x))
        elif name == "momentum_5d":
            d, w = np.sign(x["ret_5"].fillna(0).to_numpy()), np.ones(len(x))
        else:
            v = x[f"garch_h{GARCH_NEAR[h]}"].to_numpy()
            d, w = np.where(v > 0, 1.0, 0.0), np.minimum(2.0, 0.30 / np.where(v > 0, v, np.nan))
        t = x.assign(_d=d, _w=w)
        t = t[t["_d"] != 0]
        vals = []
        for s in range(20):
            y = g.one_open_trade(g2.schedule_rows(t, s, pos))
            vals.append(float(((y["_d"] * y["gross"] - y["cost"]) * y["_w"]).mean() * 100) if len(y) else float("nan"))
        out[name] = vals
    return out


def run_evaluate(controls: bool = False) -> dict:
    spec, gate = m.read_spec(), g2.read_spec()
    names = [n for n in spec["specs"] if n != "c_har_vol"]
    rep: dict = {"models_sha256": m.SPEC_SHA256, "cells": [], "item_d_percentile": m.ITEM_D_PERCENTILE}
    for h in g.HORIZONS:
        rows = pd.read_parquet(paths(DEV_END)[0] / f"rows_h{h}.parquet")
        base = {u: dev_baselines(h, u, rows) for u in ("U1",)}
        for n in names:
            rep["cells"].append(evaluate_cell(n, h, spec, gate, rows, baselines=base["U1"]))
            print(n, h, rep["cells"][-1].get("pass"), flush=True)
        rep.setdefault("baselines", {})[f"h{h}"] = {b: {"max": max(v), "min": min(v)} for b, v in base["U1"].items()}
    rep["c_har_vol"] = har_report()
    seen = {t.idea for t in trial_log.load()}
    for n in spec["specs"]:
        for h in g.HORIZONS:
            for u in ("U1", "U2"):
                idea = f"models_v1_refit1_{n}_h{h}_{u}"
                if idea not in seen:
                    trial_log.record(trial_log.Trial(idea=idea, params={"h": h, "universe": u, "models_sha256": m.SPEC_SHA256}, universe=u, data_start="2010-01-01", data_end=str(DEV_END), n_trials=1, n_oos_trades=0,
                                                     notes="development evaluation after the GARCH fix, gate v2 + addenda 1-7; cost model unverified"))
    rep["trial_count"] = trial_log.trial_count()
    (OUT / "development.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def har_report() -> dict:
    """Spec c: risk scaling only. Out-of-fold QLIKE of the HAR fit against the nearest GARCH horizon, daily variance."""
    out = {}
    panel = pd.read_parquet(paths(DEV_END)[0] / "panel.parquet")
    sessions = [date.fromisoformat(s) for s in json.loads((paths(DEV_END)[0] / "sessions.json").read_text(encoding="utf-8"))]
    for h in g.HORIZONS:
        rows = pd.read_parquet(paths(DEV_END)[0] / f"rows_h{h}.parquet")
        gcol = f"garch_h{GARCH_NEAR[h]}"
        x = rows.merge(panel[["panel_row", "rv_5", "rv_20", "rv_60", gcol]], on="panel_row", how="left")
        ok = x[["rv_5", "rv_20", "rv_60", "t3_vol"]].notna().all(axis=1) & (x["t3_vol"] > 0) & (x[["rv_5", "rv_20", "rv_60"]] > 0).all(axis=1)
        x = x[ok].reset_index(drop=True)
        q_h, q_g, n = [], [], 0
        for f in m.DEV_FOLDS:
            mask = m.fit_mask(x["entry_pos"].to_numpy(), x["exit_pos"].to_numpy(), f, h, sessions) & x["in_U1"].to_numpy()
            te = (x["fold"].to_numpy() == f) & x["in_U1"].to_numpy() & x[gcol].notna().to_numpy() & (x[gcol].to_numpy() > 0)
            if mask.sum() < 1000 or not te.any():
                continue
            X = np.log(x.loc[mask, ["rv_5", "rv_20", "rv_60"]].to_numpy(dtype=float))
            coef = np.linalg.lstsq(np.column_stack([np.ones(len(X)), X]), np.log(x.loc[mask, "t3_vol"].to_numpy()), rcond=None)[0]
            T = np.log(x.loc[te, ["rv_5", "rv_20", "rv_60"]].to_numpy(dtype=float))
            real = x.loc[te, "t3_vol"].to_numpy() ** 2
            har = np.exp(np.column_stack([np.ones(len(T)), T]) @ coef) ** 2
            gar = (x.loc[te, gcol].to_numpy() / np.sqrt(252)) ** 2
            q_h.append(float(np.mean(real / har - np.log(real / har) - 1)))
            q_g.append(float(np.mean(real / gar - np.log(real / gar) - 1)))
            n += int(te.sum())
        out[f"h{h}"] = {"qlike_har": float(np.mean(q_h)) if q_h else None, "qlike_garch": float(np.mean(q_g)) if q_g else None, "garch_horizon_used": GARCH_NEAR[h], "rows": n}
    return out


def run_controls(workers: int) -> dict:
    spec, gate = m.read_spec(), g2.read_spec()
    plan = [("a_elastic_logistic", g.HORIZONS), ("b_lightgbm", g.HORIZONS), ("f_rank", g.HORIZONS), ("d_temporal_cnn", (1, 3))]
    rep: dict = {"cells": []}
    for control in ("shuffled", "time_shift", "stale"):
        for name, hs in plan:
            run_fit([name], workers, control, hs)
        for name, hs in plan:
            for h in hs:
                rows, _ = apply_control(pd.read_parquet(paths(DEV_END)[0] / f"rows_h{h}.parquet"), pd.read_parquet(paths(DEV_END)[0] / "panel.parquet", columns=["symbol", "signal_pos", "panel_row"]), control, h) if control == "stale" else (pd.read_parquet(paths(DEV_END)[0] / f"rows_h{h}.parquet"), None)
                c = evaluate_cell(name, h, spec, gate, rows, control)
                rep["cells"].append(c)
                print(control, name, h, c.get("pass"), flush=True)
    rep["any_control_passed"] = any(c.get("pass") for c in rep["cells"])
    rep["result"] = "PASS" if not rep["any_control_passed"] else "FAIL"
    (OUT / "controls.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def run_truncation() -> dict:
    """Each learner, refit with every row after D overwritten (features and labels), gives the same predictions for D. A planted leak,
    training on those overwritten labels, must change them, so this check can fail."""
    spec = m.read_spec()
    h, fold = 1, 0
    d = load_h(h)
    rows, panel, sessions = d["rows"], d["panel"], d["sessions"]
    columns = m.allowed_columns(spec["features"], fold, d["allowed"])
    test_days = sorted(rows.loc[rows["fold"] == fold, "signal"].unique())
    days = [test_days[10], test_days[200]]
    rep: dict = {"h": h, "fold": fold, "days": [str(x)[:10] for x in days], "learners": {}}

    def fitted(name, learn, r, pn, params, extra, keep):
        tr = np.flatnonzero(keep)
        fr = frames(r.iloc[tr], pn, columns)
        return learn(fr, labels(name, r)[tr], m.Prep(fr, columns, d["groups"]), params, 11, **{**extra, "panel": {"frame": pn, "seq": d["seq"]}})

    base = m.fit_mask(rows["entry_pos"].to_numpy(), rows["exit_pos"].to_numpy(), fold, h, sessions) & rows["in_U1"].to_numpy()
    stocks = rows["kind"].to_numpy() == "stock"
    for name, learn in LEARN.items():
        params = dict(zip(spec["specs"][name]["grid"], _product(spec["specs"][name]["grid"])[0], strict=True))
        extra = {"threads": 8, "monotone": spec["specs"][name].get("monotone")}
        keep = base & stocks if name == "f_rank" else base
        cells, diffs = 0, 0
        for day in days:
            part = rows[rows["signal"] == day]
            pos = int(part["signal_pos"].iloc[0])
            r2, p2 = rows.copy(), panel.copy()
            r2.loc[r2["signal_pos"] > pos, "gross"] = 0.5
            p2.loc[p2["signal_pos"] > pos, columns] = 999.0
            a = fitted(name, learn, rows, panel, params, extra, keep)(frames(part, panel, columns))
            b = fitted(name, learn, r2, p2, params, extra, keep)(frames(part, p2, columns))
            diffs += int((~np.isclose(a, b, rtol=1e-5, atol=1e-6)).sum())
            cells += len(a)
        # the same refit, but allowed to train on the overwritten later rows: this must move the predictions
        leak_keep = keep | ((rows["signal_pos"].to_numpy() > pos) & rows["in_U1"].to_numpy() & (stocks if name == "f_rank" else True))
        y_leak = rows.assign(gross=np.where(rows["signal_pos"].to_numpy() > pos, np.abs(rows["gross"].to_numpy()) + 0.01, rows["gross"].to_numpy()))
        c = fitted(name, learn, y_leak, panel, params, extra, leak_keep)(frames(part, panel, columns))
        moved = bool((~np.isclose(a, c, rtol=1e-3, atol=1e-4)).any())
        rep["learners"][name] = {"predictions": cells, "different": diffs, "planted_leak_detected": moved}
        print(name, cells, diffs, moved, flush=True)
    rep["result"] = "PASS" if all(v["different"] == 0 and v["planted_leak_detected"] for v in rep["learners"].values()) else "FAIL"
    (OUT / "truncation.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(rep["result"], flush=True)
    return rep


def importance_job(args: tuple) -> dict:
    """Report-only. b_lightgbm with its chosen depth, seed 11: gain per feature, and out-of-fold log loss with each family removed."""
    h, fold, depth, drop = args
    d = load_h(h)
    rows, panel = d["rows"], d["panel"]
    spec = d["spec"]
    fam = {n: f["family"] for n, f in fx.read_spec()["features"].items()}
    cols = [c for c in m.allowed_columns(spec["features"], fold, d["allowed"]) if fam[c] != drop]
    mask = m.fit_mask(rows["entry_pos"].to_numpy(), rows["exit_pos"].to_numpy(), fold, h, d["sessions"]) & rows["in_U1"].to_numpy()
    tr, te = np.flatnonzero(mask), np.flatnonzero((rows["fold"].to_numpy() == fold) & rows["in_U1"].to_numpy())
    y = labels("b_lightgbm", rows)
    fr, tf = frames(rows.iloc[tr], panel, cols), frames(rows.iloc[te], panel, cols)
    predict = m.fit_lgbm_classifier(fr, y[tr], m.Prep(fr, cols, d["groups"]), {"max_depth": depth}, 11, monotone={**spec["specs"]["b_lightgbm"]["monotone"], "features": [c for c in spec["specs"]["b_lightgbm"]["monotone"]["features"] if c in cols]}, threads=THREADS)
    out = {"h": h, "fold": fold, "drop": drop, "log_loss": _loss("b_lightgbm", predict(tf), y[te].astype(float)), "rows": len(te)}
    if drop is None:
        by = predict.model.booster_.feature_importance("gain")
        fam_gain: dict = {}
        for c, v in zip(cols, by, strict=True):
            fam_gain[fam[c]] = fam_gain.get(fam[c], 0.0) + float(v)
        out["family_gain"] = fam_gain
        out["garch_gain"] = sum(float(v) for c, v in zip(cols, by, strict=True) if c.startswith("garch_"))
        out["total_gain"] = float(by.sum())
        out["top"] = sorted(zip(cols, [float(v) for v in by], strict=True), key=lambda kv: -kv[1])[:10]
    return out


def run_importance(workers: int) -> dict:
    chosen = {(c["h"], c["fold"]): c["params"]["max_depth"] for c in json.loads((OUT / "fit_b.json").read_text(encoding="utf-8")) if not c.get("skipped")}
    jobs = [(h, f, chosen[(h, f)], drop) for h in (1, 2, 3) for f in m.DEV_FOLDS if (h, f) in chosen for drop in (None, *"abcdefgh")]
    with ProcessPoolExecutor(workers) as pool:
        res = list(pool.map(importance_job, jobs))
    (OUT / "importance.json").write_text(json.dumps({"report_only": True, "rows": res}, indent=0), encoding="utf-8")
    print("importance", len(res), flush=True)
    return {"rows": res}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["prepare", "fit", "evaluate", "controls", "truncation", "importance"], required=True)
    parser.add_argument("--specs", nargs="*", default=[])
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) // THREADS - 1))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.part == "prepare":
        prepare()
    elif args.part == "fit":
        run_fit(args.specs, args.workers)
    elif args.part == "evaluate":
        run_evaluate()
    elif args.part == "truncation":
        run_truncation()
    elif args.part == "importance":
        run_importance(args.workers)
    else:
        run_controls(args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
