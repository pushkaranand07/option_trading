"""Gate v2 harness: item d calibration, self-tests, baselines under rules A and B (docs/gate_v2.json, docs/PA_40). No model.

    python scripts/research_gate2_harness.py --part calibrate      # before gate_v2.json is frozen
    python scripts/research_gate2_harness.py --part selftest
    python scripts/research_gate2_harness.py --part baselines      # logs each baseline as a trial, once

Reads base tables through research.gate.load and the action list through research.loader only: nothing from 2025-01-01 on.
Calibration and self-test series are built from development trades only. Writes reports/gate/*_v2.json (gitignored).
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

import research_gate_harness as v1  # noqa: E402

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES  # noqa: E402
from tradingagents.research import gate as g, gate2 as g2, loader, universes as uv  # noqa: E402

OUT = ROOT / "reports" / "gate"
START = date(2010, 1, 1)
DEV_END = pd.Timestamp("2022-12-31")
BLOCK_GRID = (1, 2, 3, 5, 10, 15, 20, 30)
NULLS = ("cost_random", "zero_row", "zero_date", "zero_regime")
TARGETS = (100, 150)
NULL_RUNS, PLANTED_RUNS, CONTROL_RUNS = 1000, 300, 200
HITS = (0.55, 0.60, 0.65, 0.70, 0.75)
REGIME_DATES = 20
BASELINES = v1.BASELINES


def load_rule(rule: str = "A") -> dict:
    fut = g.load("base_futures", start=START)
    summ = g.load("base_fo_summary", start=START)
    actions, months = loader.load_actions()
    f = g.clean_futures(fut)
    sessions = g.session_list(f, [d for d, k in ARCHIVE_HOLES.items() if "fo" in k])
    ev, returns = g2.prepare(f, actions, rule)
    u1, u2 = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    return {"f": f, "sessions": sessions, "events": ev, "returns": returns, "months": months, "U1": u1, "U2": u2, "rule": rule}


def trades_for(data: dict, h: int, universe: str) -> pd.DataFrame:
    t = g.build_trades(data["f"], h, data["sessions"], data["events"])
    t = g.attach_membership(t, data[universe])
    t = g.apply_min_move(t, g.expected_move(data["returns"], h))
    return g2.label_action_list(t, data["months"])


def garch_cached(data: dict, workers: int) -> pd.DataFrame:
    path = OUT / "garch_ruleA.parquet"
    if path.exists():
        return pd.read_parquet(path)
    out = v1.garch_table({"returns": data["returns"]}, workers)
    OUT.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    return out


_S: dict = {}


def _init(payload):
    _S.update(payload)


def pack(t: pd.DataFrame, returns: pd.DataFrame, garch: pd.DataFrame, h: int) -> dict:
    x = g.one_open_trade(t[pd.to_datetime(t["entry"]) <= DEV_END].copy())
    x["prev"] = g.signals_baseline("prev_day", x, returns).to_numpy()
    x["mom"] = g.signals_baseline("momentum_5d", x, returns).to_numpy()
    v = garch[["symbol", "signal", f"h{h}"]].rename(columns={f"h{h}": "vol"})
    x = x.merge(v, on=["symbol", "signal"], how="left")
    x["w"] = np.minimum(v1.MAX_WEIGHT, v1.VOL_TARGET / x["vol"].where(x["vol"] > 0))
    x = x.sort_values(["signal", "symbol"]).reset_index(drop=True)
    dates, first = np.unique(x["signal"].astype(str).to_numpy(), return_index=True)
    return {"gross": x["gross"].to_numpy(), "cost": g._costs(x["kind"], g.GATE_COST_MULTIPLE), "prev": x["prev"].to_numpy(),
            "mom": x["mom"].to_numpy(), "w": x["w"].to_numpy(), "dates": dates, "first": first, "last": np.append(first[1:], len(x)),
            "n": len(x), "mean_gross": float(x["gross"].mean())}


def _timeline(rng, n_real: int, n: int, h: int) -> np.ndarray:
    block = max(2, v1.BLOCK_SESSIONS // h)
    starts = rng.integers(0, max(1, n_real - block), size=n // block + 2)
    return ((starts[:, None] + np.arange(block)).reshape(-1)[:n]) % n_real


def _rows(p: dict, days: np.ndarray):
    idx = [np.arange(p["first"][i], p["last"][i]) for i in days]
    labels = np.repeat(np.arange(len(days)), [len(a) for a in idx])
    return (np.concatenate(idx) if idx else np.array([], dtype=int)), labels


def _null_net(kind: str, gross, cost, labels, mean_gross, rng):
    z = gross - mean_gross
    if kind == "cost_random":
        return rng.choice([-1, 1], size=len(gross)) * gross - cost
    if kind == "zero_row":
        return rng.choice([-1, 1], size=len(z)) * z
    if kind == "zero_date":
        return rng.choice([-1, 1], size=labels.max() + 1)[labels] * z
    if kind == "zero_regime":
        chunk = labels // REGIME_DATES
        return rng.choice([-1, 1], size=chunk.max() + 1)[chunk] * z
    raise ValueError(kind)


def cal_run(args) -> bool:
    h, block, kind, n, seed = args
    rng = np.random.default_rng(seed)
    p = _S[f"U1_{h}"]
    rows, labels = _rows(p, _timeline(rng, len(p["dates"]), n, h))
    net = _null_net(kind, p["gross"][rows], p["cost"][rows], labels, p["mean_gross"], rng)
    return bool(net.mean() > 0 and g.block_bootstrap_lower(labels, net, block, rng, reps=500) > 0)


def run_calibrate(workers: int) -> dict:
    data = load_rule("A")
    garch = garch_cached(data, workers)
    payload = {}
    for h in g.HORIZONS:
        payload[f"U1_{h}"] = pack(trades_for(data, h, "U1"), data["returns"], garch, h)
    table: dict = {}
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(payload,)) as pool:
        for h in g.HORIZONS:
            for block in BLOCK_GRID:
                for kind in NULLS:
                    for n in TARGETS:
                        jobs = [(h, block, kind, n, 1000 * h + 7 * block + i * 3 + n) for i in range(NULL_RUNS)]
                        rate = float(np.mean(list(pool.map(cal_run, jobs, chunksize=40))))
                        table.setdefault(str(h), {}).setdefault(str(block), {})[f"{kind}_{n}"] = rate
            print(f"h{h}: " + " ".join(f"b{b}={max(v.values()):.3f}" for b, v in table[str(h)].items()), flush=True)
    chosen = {h: next((int(b) for b, v in t.items() if max(v.values()) <= 0.05), None) for h, t in table.items()}
    report = {"grid": BLOCK_GRID, "nulls": NULLS, "runs_per_cell": NULL_RUNS, "chosen": chosen, "table": table,
              "worst_at_chosen": {h: (max(table[h][str(b)].values()) if b else None) for h, b in chosen.items()}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calibration_v2.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("chosen", chosen, report["worst_at_chosen"])
    return report


# ---------------------------------------------------------------- self-tests

def shift_dates(values: np.ndarray, labels: np.ndarray, s: int) -> np.ndarray:
    """Each row takes the value of the row at the same position, ``s`` dates earlier on the timeline (circular). One
    timeline date is at least one session, so s dates cover at least s sessions."""
    sizes = np.bincount(labels)
    first = np.r_[0, np.cumsum(sizes)[:-1]]
    source = (labels - s) % len(sizes)
    return values[first[source] + (np.arange(len(labels)) - first[labels]) % sizes[source]]


def one_run(args) -> dict:
    h, hit, n, seed, mode = args
    rng = np.random.default_rng(seed)
    p1, p2 = _S[f"U1_{h}"], _S[f"U2_{h}"]
    n_real = len(p1["dates"])
    per_fold = max(g2.MIN_DATES, int(round(n_real / 5)))
    hist = _timeline(rng, n_real, per_fold * len(g.FOLDS), h)
    rows, labels = _rows(p1, hist)
    days = _timeline(rng, n_real, n, h)
    out_rows, lab = _rows(p1, days)
    zero = mode == "null_zero"

    def direction(gross, draw):
        if hit is None:
            return draw.choice([-1, 1], size=len(gross))
        right = draw.random(len(gross)) < hit
        s = np.where(gross >= 0, 1, -1)
        return np.where(right, s, -s)

    def net_of(gross, cost, d):
        return d * (gross - p1["mean_gross"]) if zero else d * gross - cost

    gh, ch = p1["gross"][rows], p1["cost"][rows]
    dh = direction(gh, rng)
    gr, co = p1["gross"][out_rows], p1["cost"][out_rows]
    df = direction(gr, np.random.default_rng(seed + 1))
    if mode == "shuffled":
        dh, df = rng.permutation(dh), rng.permutation(df)
    elif mode == "time_shift":
        dh = np.roll(dh, int(np.median(np.bincount(labels))) * 3)
        df = np.roll(df, int(np.median(np.bincount(lab))) * 3)
    elif mode.startswith("shift_dates_"):
        s = int(mode.rsplit("_", 1)[1])
        dh, df = shift_dates(dh, labels, s), shift_dates(df, lab, s)
    wf = {"fold": (labels // per_fold).clip(max=len(g.FOLDS) - 1), "date": labels, "net": net_of(gh, ch, dh), "n_folds": len(g.FOLDS)}
    net = net_of(gr, co, df)
    win_null = ((gr - co > 0).astype(float) + (-gr - co > 0).astype(float)) / 2
    prev, mom, w = p1["prev"][out_rows], p1["mom"][out_rows], p1["w"][out_rows]
    has_w = np.isfinite(w)
    base = {"always_long": float((gr - co).mean()), "always_short": float((-gr - co).mean()),
            "prev_day": float(np.mean((prev * gr - co)[prev != 0])), "momentum_5d": float(np.mean((mom * gr - co)[mom != 0])),
            "garch_risk_scaled": float(np.mean(((gr - co) * w)[has_w])) if has_w.any() else float("-inf")}
    u2_days = np.searchsorted(p2["dates"], p1["dates"][days])
    u2_rows, _ = _rows(p2, u2_days[u2_days < len(p2["dates"])])
    u2d = direction(p2["gross"][u2_rows], np.random.default_rng(seed + 3))
    u2_exp = float((u2d * p2["gross"][u2_rows] - p2["cost"][u2_rows]).mean())
    block = _S["block"][h]
    res = g2.evaluate({"date": lab, "net": net, "win_null": win_null}, wf, base, u2_exp, h, _S["x"][h], block, rng, reps=500)
    return {k: bool(res[k]["pass"]) for k in "abcdefg"} | {"tier1": bool(res["tier1"]), "tier2": bool(res["tier2"]),
            "win": res["b"]["win_rate"], "exp": res["d"]["expectancy"], "raw": res["a"]["raw"], "dates": res["a"]["distinct_dates"],
            "min_fold_dates": res["g"]["min_fold_dates"]}


def summarize(rows: list[dict]) -> dict:
    out = {"runs": len(rows), "tier1_rate": float(np.mean([r["tier1"] for r in rows])), "tier2_rate": float(np.mean([r["tier2"] for r in rows]))}
    out |= {f"item_{k}_rate": float(np.mean([r[k] for r in rows])) for k in "abcdefg"}
    out |= {f"mean_{k}": float(np.nanmean([r[k] for r in rows])) for k in ("win", "exp", "raw", "dates", "min_fold_dates")}
    return out


def run_selftests(workers: int) -> dict:
    from tradingagents.research.gate2 import read_spec

    spec = read_spec()
    data = load_rule("A")
    garch = garch_cached(data, workers)
    payload = {"x": {h: spec["gate"]["g"]["x_h_percent"][str(h)] / 100 for h in g.HORIZONS},
               "block": {h: spec["gate"]["d"]["block_dates_by_h"][str(h)] for h in g.HORIZONS}}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            payload[f"{uni}_{h}"] = pack(trades_for(data, h, uni), data["returns"], garch, h)
    rep = {"label": "development trades, rule A; cost model unverified", "gate_sha256": g2.GATE_SHA256, "null": {}, "null_zero": {}, "planted": {}, "controls": {}}
    t0 = time.monotonic()
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(payload,)) as pool:
        for h in g.HORIZONS:
            for n in TARGETS:
                for mode, key in (("null", "null"), ("null_zero", "null_zero")):
                    rows = list(pool.map(one_run, [(h, None, n, 10_000 * h + i + n, mode) for i in range(NULL_RUNS)], chunksize=10))
                    rep[key].setdefault(f"h{h}", {})[f"n{n}"] = summarize(rows)
            print(f"null h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for hit in HITS:
                for n in TARGETS:
                    rows = list(pool.map(one_run, [(h, hit, n, 7_000_000 + int(hit * 100) * 1000 + n + i * 7 + h, "planted") for i in range(PLANTED_RUNS)], chunksize=10))
                    rep["planted"].setdefault(f"h{h}", {})[f"hit{hit:.2f}_n{n}"] = summarize(rows)
            print(f"planted h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for mode in ("control_oracle", "shuffled", "time_shift"):
                rows = list(pool.map(one_run, [(h, 0.90, 100, 9_000_000 + i + h, mode) for i in range(CONTROL_RUNS)], chunksize=10))
                rep["controls"].setdefault(f"h{h}", {})[mode] = summarize(rows)
            print(f"controls h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
    # the chosen blocks on fresh seeds: item d alone, on all four nulls
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(payload,)) as pool:
        for h in g.HORIZONS:
            for kind in NULLS:
                for n in TARGETS:
                    jobs = [(h, payload["block"][h], kind, n, 50_000_000 + 100_000 * h + i) for i in range(NULL_RUNS)]
                    rep.setdefault("item_d_fresh_seeds", {}).setdefault(f"h{h}", {})[f"{kind}_{n}"] = float(np.mean(list(pool.map(cal_run, jobs, chunksize=40))))
    (OUT / "selftests_v2.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


# ---------------------------------------------------------------- baselines

def measure(x: pd.DataFrame, direction, weight, sessions: pd.Series) -> dict:
    """One baseline's numbers per period, with and without trades that have no action list."""
    cell = {}
    entry = pd.to_datetime(x["entry"])
    for per, mask in (("development", entry <= DEV_END), ("validation", entry > DEV_END)):
        for cov, sub in (("all", np.ones(len(x), dtype=bool)), ("with_action_list", x["has_action_list"].to_numpy())):
            m = mask.to_numpy() & sub
            y, dd, ww = x[m], direction[m], weight[m]
            if not len(y):
                cell.setdefault(per, {})[cov] = {"raw_trades": 0}
                continue
            nets = {str(c): g.net_returns(y, dd, c, ww) for c in (1.0, 1.5, 2.0)}
            n15 = nets["1.5"]
            dates = y["signal"].astype(str).to_numpy()
            d = pd.to_datetime(y["entry"])
            weeks = (d.max() - d.min()).days / 7
            k = len(np.unique(dates))
            span = int(((sessions >= d.min()) & (sessions <= d.max())).sum())
            rate = k / weeks if weeks else float("nan")
            cell.setdefault(per, {})[cov] = {
                "raw_trades": len(y), "distinct_dates": k, "effective_v1": g.effective_count(dates, n15), "weeks": weeks,
                "dates_per_week": rate, "dates_per_session": k / span if span else None,
                "weeks_to_100": 100 / rate if rate else None, "weeks_to_150": 150 / rate if rate else None,
                **{f"expectancy_{c}x_pct": float(v.mean() * 100) for c, v in nets.items()},
                **{f"win_rate_{c}x": float((v > 0).mean()) for c, v in nets.items()},
                "median_1.5x_pct": float(np.median(n15) * 100), "winsorized_1.5x_pct": g2.winsorized_mean(n15) * 100}
    return cell


def run_baselines(workers: int) -> dict:
    seen = {t.idea for t in trial_log.load()}
    rep: dict = {"label": "cost model unverified; slippage ASSUMPTION; known_from of the action list UNVERIFIED"}
    for rule in ("A", "B"):
        data = load_rule(rule)
        garch = garch_cached(load_rule("A") if rule != "A" else data, workers)
        sessions = pd.to_datetime(pd.Series(data["sessions"]))
        for h in g.HORIZONS:
            for uni in ("U1", "U2"):
                t = trades_for(data, h, uni)
                for name in BASELINES:
                    x, direction, weight = v1.baseline_rows(name, t, data["returns"], garch, h)
                    cell = measure(x, direction, weight, sessions)
                    rep.setdefault(rule, {}).setdefault(f"h{h}", {}).setdefault(uni, {})[name] = cell
                    idea = f"gate_v2_baseline_{name}_h{h}_{uni}_rule{rule}"
                    if idea not in seen:
                        trial_log.record(trial_log.Trial(idea=idea, params={"h": h, "universe": uni, "rule": rule, "gate_sha256": g2.GATE_SHA256}, universe=uni,
                                                         data_start=str(x["entry"].min()), data_end=str(x["exit"].max()), n_trials=1, n_oos_trades=len(x),
                                                         notes="baseline measurement, not a model; cost model unverified"))
                print(f"rule {rule} h{h} {uni}", flush=True)
    rep["trial_count"] = trial_log.trial_count()
    trial_log.log_event("validation_seen", {"for": "gate item e baselines under gate v2 rules A and B", "period": "2023-2024",
                                            "note": "validation is still used once per frozen model spec", "gate_sha256": g2.GATE_SHA256})
    (OUT / "baselines_v2.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["calibrate", "selftest", "baselines"], required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    {"calibrate": run_calibrate, "selftest": run_selftests, "baselines": run_baselines}[args.part](args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
