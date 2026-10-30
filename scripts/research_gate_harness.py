"""Gate v1 harness: self-tests and the baseline measurement (docs/gate_v1.json, docs/PA_39). No model is built.

    python scripts/research_gate_harness.py --part selftest
    python scripts/research_gate_harness.py --part baselines      # logs each baseline as a trial, once

Reads base tables through research.gate.load only, which holds no unlock: nothing from 2025-01-01 on can be read. Self-test
series are built from development trades only (entries to 2022). Writes reports/gate/*.json (gitignored).
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

from tradingagents.analytics import (  # noqa: E402
    trial_log,  # noqa: E402
    volatility_model as vm,  # noqa: E402
)
from tradingagents.dataflows.vendors.nse.calendar import ARCHIVE_HOLES  # noqa: E402
from tradingagents.research import (  # noqa: E402
    gate as g,  # noqa: E402
    universes as uv,  # noqa: E402
)

OUT = ROOT / "reports" / "gate"
START = date(2010, 1, 1)
BASELINES = ("always_long", "always_short", "prev_day", "momentum_5d", "garch_risk_scaled")
REFIT = 63
VOL_TARGET = 0.30
MAX_WEIGHT = 2.0
DEV_END = pd.Timestamp("2022-12-31")
NULL_RUNS, PLANTED_RUNS, CONTROL_RUNS = 1000, 300, 200
PLANTED_HIT_RATES = (0.55, 0.60, 0.65, 0.70, 0.75)
BLOCK_SESSIONS = 20


def load_all() -> dict:
    spec = g.read_spec()
    fut = g.load("base_futures", start=START)
    summ = g.load("base_fo_summary", start=START)
    f = g.clean_futures(fut)
    holes = [d for d, k in ARCHIVE_HOLES.items() if "fo" in k]
    sessions = g.session_list(f, holes)
    events = g.split_events(f)
    returns = g.daily_returns(f, events)
    u1, u2 = g.universe_members(summ, pd.read_csv(uv.SYMBOL_MAP))
    return {"spec": spec, "f": f, "sessions": sessions, "events": events, "returns": returns, "U1": u1, "U2": u2}


def _garch_one(args) -> pd.DataFrame:
    symbol, r = args
    close = (1 + r).cumprod()
    lr = vm.log_returns(close)
    try:
        fc = vm.garch_forecasts(lr, "garch", horizons=g.HORIZONS, refit_every=REFIT)
    except Exception:          # a symbol GARCH cannot fit has no forecast and no baseline trade
        return pd.DataFrame()
    return fc.reset_index(names="signal").assign(symbol=symbol)


def garch_table(data: dict, workers: int) -> pd.DataFrame:
    r = data["returns"].copy()
    r["d"] = pd.to_datetime(r["trade_date"])
    jobs = [(s, x.set_index("d")["ret"]) for s, x in r.groupby("symbol") if len(x) > 600]
    with ProcessPoolExecutor(workers) as pool:
        parts = [p for p in pool.map(_garch_one, jobs, chunksize=4) if len(p)]
    out = pd.concat(parts, ignore_index=True)
    out["signal"] = pd.to_datetime(out["signal"]).dt.date
    return out


def trades_for(data: dict, h: int, universe: str) -> pd.DataFrame:
    t = g.build_trades(data["f"], h, data["sessions"], data["events"])
    t = g.attach_membership(t, data[universe])
    return g.apply_min_move(t, g.expected_move(data["returns"], h))


def baseline_rows(name: str, t: pd.DataFrame, returns: pd.DataFrame, garch: pd.DataFrame | None, h: int) -> tuple:
    """(trades after the one-open rule, direction, weight)."""
    if name == "garch_risk_scaled":
        v = garch[["symbol", "signal", f"h{h}"]].rename(columns={f"h{h}": "vol"})
        x = t.merge(v, on=["symbol", "signal"], how="inner")
        x = x[x["vol"] > 0]
        x = g.one_open_trade(x)
        return x, np.ones(len(x)), np.minimum(MAX_WEIGHT, VOL_TARGET / x["vol"].to_numpy())
    d = g.signals_baseline(name, t, returns)
    x = t.assign(_d=d.to_numpy())
    x = x[x["_d"] != 0]
    x = g.one_open_trade(x)
    return x, x["_d"].to_numpy(), np.ones(len(x))


# ---------------------------------------------------------------- baselines (step 8)

def run_baselines(workers: int) -> dict:
    data = load_all()
    print("loaded; last trade date", data["f"]["trade_date"].max(), flush=True)
    garch = garch_table(data, workers)
    print("garch symbols", garch["symbol"].nunique(), flush=True)
    seen = {t.idea for t in trial_log.load()}
    report = {}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            t = trades_for(data, h, uni)
            for name in BASELINES:
                x, direction, weight = baseline_rows(name, t, data["returns"], garch, h)
                row = {}
                for label, mask in (("development", pd.to_datetime(x["entry"]) <= DEV_END),
                                    ("validation", pd.to_datetime(x["entry"]) > DEV_END)):
                    y, dd, ww = x[mask], direction[mask.to_numpy()], weight[mask.to_numpy()]
                    d = pd.to_datetime(y["entry"])
                    weeks = (d.max() - d.min()).days / 7 if len(y) else float("nan")
                    nets = {str(m): g.net_returns(y, dd, m, ww) for m in (1.0, 1.5, 2.0)}
                    eff = g.effective_count(y["signal"].astype(str).to_numpy(), nets["1.5"])
                    rate = eff / weeks if weeks else float("nan")
                    row[label] = {"raw_trades": len(y), "effective_trades": eff, "weeks": weeks,
                                  "effective_per_week": rate,
                                  "weeks_to_100": 100 / rate if rate else None, "weeks_to_150": 150 / rate if rate else None,
                                  **{f"expectancy_{m}x_pct": float(v.mean() * 100) for m, v in nets.items()},
                                  **{f"win_rate_{m}x": float((v > 0).mean()) for m, v in nets.items()}}
                report.setdefault(f"h{h}", {}).setdefault(uni, {})[name] = row
                idea = f"gate_v1_baseline_{name}_h{h}_{uni}"
                if idea not in seen:
                    trial_log.record(trial_log.Trial(idea=idea, params={"h": h, "universe": uni, "gate_sha256": g.GATE_SHA256},
                                                     universe=uni, data_start=str(x["entry"].min()), data_end=str(x["exit"].max()),
                                                     n_trials=1, n_oos_trades=len(x), notes="baseline measurement, not a model; cost model unverified"))
            print(f"h{h} {uni} done", flush=True)
    report["trial_count"] = trial_log.trial_count()
    report["bonferroni_threshold"] = 0.05 / report["trial_count"]
    report["label"] = "cost model unverified; slippage ASSUMPTION"
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "baselines.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


# ---------------------------------------------------------------- self-tests (steps 6.1 to 6.3)

_S: dict = {}


def _pack(t: pd.DataFrame, returns: pd.DataFrame) -> dict:
    """Development trades on one schedule (always a trade, one open per underlying), as arrays grouped by signal date."""
    x = g.one_open_trade(t[pd.to_datetime(t["entry"]) <= DEV_END].copy())
    x["prev"] = g.signals_baseline("prev_day", x, returns).to_numpy()
    x["mom"] = g.signals_baseline("momentum_5d", x, returns).to_numpy()
    x = x.sort_values(["signal", "symbol"]).reset_index(drop=True)
    dates, first = np.unique(x["signal"].astype(str).to_numpy(), return_index=True)
    return {"gross": x["gross"].to_numpy(), "cost": g._costs(x["kind"], g.GATE_COST_MULTIPLE), "prev": x["prev"].to_numpy(),
            "mom": x["mom"].to_numpy(), "dates": dates, "first": first, "last": np.append(first[1:], len(x)), "n": len(x),
            "symbol": x["symbol"].to_numpy()}


def _init(payload):
    _S.update(payload)


def _rows(p: dict, day_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Row indices and the synthetic date label (position in the resampled timeline) for chosen dates."""
    idx = [np.arange(p["first"][i], p["last"][i]) for i in day_idx]
    labels = np.repeat(np.arange(len(day_idx)), [len(a) for a in idx])
    return (np.concatenate(idx) if idx else np.array([], dtype=int)), labels


def _direction(rng, gross: np.ndarray, hit: float | None) -> np.ndarray:
    if hit is None:
        return rng.choice([-1, 1], size=len(gross))
    right = rng.random(len(gross)) < hit
    s = np.where(gross >= 0, 1, -1)
    return np.where(right, s, -s)


def _timeline(rng, n_real: int, n: int, block: int) -> np.ndarray:
    """Moving-block resample of real signal dates: keeps the cross-section of each date and short-run autocorrelation."""
    starts = rng.integers(0, max(1, n_real - block), size=n // block + 2)
    return (starts[:, None] + np.arange(block)).reshape(-1)[:n] % n_real


def one_run(args) -> dict:
    h, hit, target, seed, mode = args
    rng = np.random.default_rng(seed)
    p1, p2 = _S[f"U1_{h}"], _S[f"U2_{h}"]
    n_real = len(p1["dates"])
    block = max(2, BLOCK_SESSIONS // h)
    per_fold = max(1, int(round(n_real / 5)))         # development spans five test folds' worth of dates per fold
    hist_days = _timeline(rng, n_real, per_fold * len(g.FOLDS), block)
    rows, labels = _rows(p1, hist_days)
    gross, cost = p1["gross"][rows], p1["cost"][rows]
    d = _direction(rng, gross, hit)
    if mode == "shuffled":
        d = rng.permutation(d)
    elif mode == "time_shift":
        d = np.roll(d, int(np.median(np.bincount(labels))) * 3)     # the signal applied to other dates
    wf = {"fold": (labels // per_fold).clip(max=len(g.FOLDS) - 1), "date": labels, "net": d * gross - cost, "n_folds": len(g.FOLDS)}
    # forward: add dates until the effective count reaches the target
    days = _timeline(rng, n_real, 4000 // max(1, h), block)
    n, net, out_rows, lab, dirn = 8, None, None, None, None
    while True:
        out_rows, lab = _rows(p1, days[:n])
        gr, co = p1["gross"][out_rows], p1["cost"][out_rows]
        dirn = _direction(np.random.default_rng(seed + 1), gr, hit)
        if mode == "shuffled":
            dirn = np.random.default_rng(seed + 2).permutation(dirn)
        elif mode == "time_shift":
            dirn = np.roll(dirn, int(np.median(np.bincount(lab))) * 3)
        net = dirn * gr - co
        if g.effective_count(lab, net) >= target or n >= len(days):
            break
        n = min(len(days), int(n * 1.25) + 1)
    win_null = ((gr - co > 0).astype(float) + (-gr - co > 0).astype(float)) / 2
    base = {"always_long": float((gr - co).mean()), "always_short": float((-gr - co).mean()),
            "prev_day": float(np.mean((p1["prev"][out_rows] * gr - co)[p1["prev"][out_rows] != 0])),
            "momentum_5d": float(np.mean((p1["mom"][out_rows] * gr - co)[p1["mom"][out_rows] != 0]))}
    u2_days = np.searchsorted(p2["dates"], p1["dates"][days[:n]])          # the same real dates as U1
    u2_rows, _ = _rows(p2, u2_days[(u2_days < len(p2["dates"]))])
    u2_d = _direction(np.random.default_rng(seed + 3), p2["gross"][u2_rows], hit)
    u2_exp = float((u2_d * p2["gross"][u2_rows] - p2["cost"][u2_rows]).mean())
    res = g.evaluate({"date": lab, "net": net, "win_null": win_null}, wf, base, u2_exp, h, _S["x"][h], rng, reps=300)
    return {k: bool(res[k]["pass"]) for k in "abcdefg"} | {"passed": bool(res["passed"]),
            "win": res["b"]["win_rate"], "exp": res["d"]["expectancy"], "raw": res["a"]["raw"], "eff": res["a"]["effective"],
            "min_fold_eff": res["g"]["min_effective"]}


def summarize(rows: list[dict]) -> dict:
    out = {"runs": len(rows), "gate_pass_rate": float(np.mean([r["passed"] for r in rows]))}
    for k in "abcdefg":
        out[f"item_{k}_rate"] = float(np.mean([r[k] for r in rows]))
    out["forward_items_a_to_f_rate"] = float(np.mean([all(r[k] for k in "abcdef") for r in rows]))
    for k in ("win", "exp", "raw", "eff", "min_fold_eff"):
        out[f"mean_{k}"] = float(np.nanmean([r[k] for r in rows]))
    return out


def run_selftests(workers: int) -> dict:
    data = load_all()
    spec = data["spec"]
    payload = {"x": {h: spec["gate"]["g"]["x_h_percent"][str(h)] / 100 for h in g.HORIZONS}}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            payload[f"{uni}_{h}"] = _pack(trades_for(data, h, uni), data["returns"])
        print(f"packed h{h}: {payload[f'U1_{h}']['n']:,} U1 rows, {len(payload[f'U1_{h}']['dates'])} dates", flush=True)
    report = {"label": "built from development trades only; cost model unverified", "gate_sha256": g.GATE_SHA256,
              "null": {}, "planted": {}, "controls": {}}
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(payload,)) as pool:
        for h in g.HORIZONS:
            t0 = time.monotonic()
            rows = list(pool.map(one_run, [(h, None, 100, 1000 * h + i, "null") for i in range(NULL_RUNS)], chunksize=10))
            report["null"][f"h{h}"] = summarize(rows)
            print(f"null h{h}: false-pass {report['null'][f'h{h}']['gate_pass_rate']:.4f} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for hit in PLANTED_HIT_RATES:
                for target in (100, 150):
                    rows = list(pool.map(one_run, [(h, hit, target, 5_000_000 + int(hit * 100) * 1000 + target + i * 7 + h, "planted")
                                                   for i in range(PLANTED_RUNS)], chunksize=10))
                    report["planted"].setdefault(f"h{h}", {})[f"hit{hit:.2f}_n{target}"] = summarize(rows)
            print(f"planted h{h} done", flush=True)
        for h in g.HORIZONS:
            for mode, hit in (("control_oracle", 0.90), ("shuffled", 0.90), ("time_shift", 0.90)):
                rows = list(pool.map(one_run, [(h, hit, 100, 9_000_000 + i + h, mode) for i in range(CONTROL_RUNS)], chunksize=10))
                report["controls"].setdefault(f"h{h}", {})[mode] = summarize(rows)
            print(f"controls h{h} done", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "selftests.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["selftest", "baselines"], required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    if args.part == "selftest":
        run_selftests(args.workers)
    else:
        run_baselines(args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
