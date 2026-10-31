"""Gate v2 addendum 4 measurements: baselines on many trade schedules, and item d and the pass at 2 and 3 specs (docs/PA_45). No model.

    python scripts/research_gate2_addendum4.py --part schedules     # logs each validation read as a trial, once
    python scripts/research_gate2_addendum4.py --part power         # needs the schedules report; development trades only

Schedules: rule A, D-1 timing, 20 start offsets per symbol, restarted in each period, so an offset cannot fade before validation. Also
schedule ranges on 100-session development windows, the length of a forward test. Writes reports/gate/addendum4_*.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import research_gate2_addendum as a1  # noqa: E402
import research_gate2_harness as h2  # noqa: E402

from tradingagents.analytics import trial_log  # noqa: E402
from tradingagents.research import gate as g, gate2 as g2  # noqa: E402

OUT = ROOT / "reports" / "gate"
OFFSETS = range(20)
WINDOWS, WINDOW_SESSIONS = 20, 100
PERCENTILES = {"1_spec": 2.5, "2_specs": 1.25, "3_specs": 2.5 / 3}
NULL_RUNS = POWER_RUNS = 5000
RULE_RUNS = 1000
_D: dict = {}


def _init_schedules() -> None:
    data = h2.load_rule("A")
    _D["data"] = data
    _D["lag"] = g2.lag_one_session(data["returns"], data["sessions"], "trade_date")
    _D["garch"] = g2.lag_one_session(pd.read_parquet(OUT / "garch_ruleA.parquet"), data["sessions"], "signal")


def baseline_frames(h: int, uni: str) -> dict[str, pd.DataFrame]:
    """Each baseline's candidate rows on D-1 timing, before the one-open rule, with direction and weight."""
    data, lag, garch = _D["data"], _D["lag"], _D["garch"]
    t = g.build_trades(data["f"], h, data["sessions"], data["events"])
    t = g.attach_membership(t, data[uni])
    t = g.apply_min_move(t, g.expected_move(lag, h))
    out = {}
    for name in h2.BASELINES:
        if name == "garch_risk_scaled":
            v = garch[["symbol", "signal", f"h{h}"]].rename(columns={f"h{h}": "vol"})
            x = t.merge(v, on=["symbol", "signal"], how="inner")
            x = x[x["vol"] > 0].assign(_d=1.0)
            x["_w"] = np.minimum(h2.v1.MAX_WEIGHT, h2.v1.VOL_TARGET / x["vol"].to_numpy())
        else:
            x = t.assign(_d=g.signals_baseline(name, t, lag).to_numpy(), _w=1.0)
            x = x[x["_d"] != 0]
        out[name] = x.drop(columns="vol", errors="ignore").reset_index(drop=True)
    return out


def one_schedule(x: pd.DataFrame, offset: int, position: dict) -> dict:
    y = g.one_open_trade(g2.schedule_rows(x, offset, position))
    if not len(y):
        return {"net_pct": float("nan"), "trades": 0, "key": ""}
    net = g.net_returns(y, y["_d"].to_numpy(), g.GATE_COST_MULTIPLE, y["_w"].to_numpy())
    key = hashlib.sha1("".join(sorted(y["symbol"].astype(str) + y["signal"].astype(str))).encode()).hexdigest()
    return {"net_pct": float(net.mean() * 100), "win": float((net > 0).mean()), "trades": len(y), "dates": int(y["signal"].nunique()), "key": key}


def summary(rows: list[dict]) -> dict:
    v = np.array([r["net_pct"] for r in rows])
    return {"schedules": len(rows), "distinct": len({r["key"] for r in rows}), "min": float(np.nanmin(v)), "max": float(np.nanmax(v)), "mean": float(np.nanmean(v)),
            "width": float(np.nanmax(v) - np.nanmin(v)), "upper_minus_mean": float(np.nanmax(v) - np.nanmean(v)), "offset_0": float(v[0]), "trades_min": min(r["trades"] for r in rows),
            "values": [float(a) for a in v]}


def schedules_job(job: tuple[int, str]) -> tuple[int, str, dict]:
    h, uni = job
    data = _D["data"]
    position = {d: i for i, d in enumerate(data["sessions"])}
    frames = baseline_frames(h, uni)
    cell: dict = {}
    for name, x in frames.items():
        entry = pd.to_datetime(x["entry"])
        for per, mask in (("development", entry <= h2.DEV_END), ("validation", entry > h2.DEV_END)):
            sub = x[mask.to_numpy()]
            cell.setdefault(name, {})[per] = summary([one_schedule(sub, s, position) for s in OFFSETS])
        if uni == "U1":      # 100-session development windows: the length of a forward test
            rng = np.random.default_rng(1000 + h)
            dev = x[(entry <= h2.DEV_END).to_numpy()]
            days = sorted(set(dev["signal"]))
            starts = rng.integers(0, len(days) - WINDOW_SESSIONS, size=WINDOWS)
            widths, uppers = [], []
            for st in starts:
                part = dev[dev["signal"].isin(days[st:st + WINDOW_SESSIONS])]
                s = summary([one_schedule(part, k, position) for k in OFFSETS])
                widths.append(s["width"])
                uppers.append(s["upper_minus_mean"])
            cell[name]["window_100"] = {"windows": WINDOWS, "median_width": float(np.nanmedian(widths)), "p90_width": float(np.nanpercentile(widths, 90)),
                                        "median_upper_minus_mean": float(np.nanmedian(uppers)), "p90_upper_minus_mean": float(np.nanpercentile(uppers, 90))}
    print(f"h{h} {uni}", flush=True)
    return h, uni, cell


def run_schedules(workers: int) -> dict:
    seen ={t.idea for t in trial_log.load()}
    t0 = time.monotonic()
    jobs = [(h, u) for h in g.HORIZONS for u in ("U1", "U2")]
    rep: dict = {"label": "D-1 timing, rule A; 20 start offsets per symbol, restarted in each period; cost model unverified; slippage ASSUMPTION", "cells": {}}
    with ProcessPoolExecutor(min(workers, 5), initializer=_init_schedules) as pool:
        for h, uni, cell in pool.map(schedules_job, jobs):
            rep["cells"].setdefault(f"h{h}", {})[uni] = cell
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            for name in h2.BASELINES:
                for s in OFFSETS:
                    idea = f"gate_v2_addendum4_baseline_schedule_{name}_h{h}_{uni}_offset{s}"
                    if idea not in seen:
                        trial_log.record(trial_log.Trial(idea=idea, params={"h": h, "universe": uni, "offset": s, "timing": "D-1", "gate_sha256": g2.GATE_SHA256}, universe=uni,
                                                         data_start="2010-01-01", data_end="2024-12-31", n_trials=1, n_oos_trades=0,
                                                         notes="validation read; baseline on one trade schedule, not a model; cost model unverified"))
    rep["trial_count"] = trial_log.trial_count()
    trial_log.log_event("validation_seen", {"for": "gate item e baselines on 20 trade schedules, addendum 4", "period": "2023-2024", "trials_logged": 2000, "gate_sha256": g2.GATE_SHA256})
    (OUT / "addendum4_schedules.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(f"schedules {time.monotonic() - t0:.0f}s, trials {rep['trial_count']}")
    return rep


# ---------------------------------------------------------------- power

def cal_percentiles(args) -> dict:
    h, block, kind, n, seed = args
    rng = np.random.default_rng(seed)
    p = h2._S[f"U1_{h}"]
    rows, labels = h2._rows(p, h2._timeline(rng, len(p["dates"]), n, h))
    net = h2._null_net(kind, p["gross"][rows], p["cost"][rows], labels, p["mean_gross"], rng)
    low = g2.bootstrap_lowers(labels, net, block, rng, PERCENTILES, reps=g.BOOTSTRAP_REPS)
    return {k: bool(net.mean() > 0 and v > 0) for k, v in low.items()}


def cell_rates(rows: list[dict], offsets: dict) -> dict:
    out: dict = {"mean_win": float(np.nanmean([r["win"] for r in rows]))}
    core = np.array([r["a"] and r["f"] and r["g"] for r in rows])
    exp = np.array([r["exp"] for r in rows])
    for k in PERCENTILES:
        d = np.array([r["d_by_spec"][k] for r in rows])
        out[f"item_d_{k}"] = a1.rate(d.tolist())
        for label, off in offsets.items():
            e = np.array([all(x > r["base"][b] + off[b] for b in r["base"]) for x, r in zip(exp, rows, strict=True)])
            out[f"pass_{k}_{label}"] = a1.rate((core & d & e).tolist())
    return out


def rule_offsets(cell: dict) -> dict:
    """How far each baseline's upper range sits above its mean, as a fraction: the schedule report is in percent, expectancies are not."""
    names = list(cell)
    return {"one_schedule": dict.fromkeys(names, 0.0), "upper_development": {b: cell[b]["development"]["upper_minus_mean"] / 100 for b in names},
            "upper_validation": {b: cell[b]["validation"]["upper_minus_mean"] / 100 for b in names}, "upper_100_session": {b: cell[b]["window_100"]["median_upper_minus_mean"] / 100 for b in names},
            "upper_100_session_p90": {b: cell[b]["window_100"]["p90_upper_minus_mean"] / 100 for b in names}}


def run_power(workers: int, rule_only: bool = False) -> dict:
    sched = json.loads((OUT / "addendum4_schedules.json").read_text(encoding="utf-8"))["cells"]
    spec = g2.read_spec()
    data = h2.load_rule("A")
    garch = h2.garch_cached(data, workers)
    payload = {"x": {h: spec["gate"]["g"]["x_h_percent"][str(h)] / 100 for h in g.HORIZONS}, "block": {h: spec["gate"]["d"]["block_dates_by_h"][str(h)] for h in g.HORIZONS},
               "lower_percentiles": PERCENTILES}
    for h in g.HORIZONS:
        for uni in ("U1", "U2"):
            payload[f"{uni}_{h}"] = h2.pack(h2.trades_for(data, h, uni), data["returns"], garch, h)
    rep: dict = {"label": "development trades, rule A; cost model unverified", "item_d_alone": {}, "null": {}, "planted": {}}
    t0 = time.monotonic()
    rep["offsets"] = {f"h{h}": rule_offsets(sched[f"h{h}"]["U1"]) for h in g.HORIZONS}
    with ProcessPoolExecutor(workers, initializer=h2._init, initargs=(payload,)) as pool:
        if rule_only:
            for h in g.HORIZONS:
                for hit in h2.HITS:
                    for n in h2.TARGETS:
                        jobs = [(h, hit, n, 1_600_000_000 + 1_000_000 * h + int(hit * 100) * 10_000 + n + i * 7, "planted") for i in range(RULE_RUNS)]
                        rep["planted"].setdefault(f"h{h}", {})[f"hit{hit:.2f}_n{n}"] = cell_rates(list(pool.map(h2.one_run, jobs, chunksize=20)), rep["offsets"][f"h{h}"])
                print(f"rule h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
            (OUT / "addendum4_rule_power.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
            return rep
        for h in g.HORIZONS:
            for ki, kind in enumerate(h2.NULLS):
                for n in h2.TARGETS:
                    jobs = [(h, payload["block"][h], kind, n, 1_200_000_000 + 10_000_000 * h + 1_000_000 * ki + 100_000 * (n // 50) + i) for i in range(NULL_RUNS)]
                    r = list(pool.map(cal_percentiles, jobs, chunksize=100))
                    rep["item_d_alone"].setdefault(f"h{h}", {})[f"{kind}_{n}"] = {k: a1.rate([x[k] for x in r]) for k in PERCENTILES}
            print(f"item d h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
        for h in g.HORIZONS:
            for mi, mode in enumerate(("null", "null_zero")):
                for n in h2.TARGETS:
                    jobs = [(h, None, n, 1_400_000_000 + 10_000_000 * h + 1_000_000 * mi + 100_000 * (n // 50) + i * 5, mode) for i in range(NULL_RUNS)]
                    rep["null"].setdefault(f"h{h}", {})[f"{mode}_{n}"] = cell_rates(list(pool.map(h2.one_run, jobs, chunksize=20)), rep["offsets"][f"h{h}"])
            print(f"null h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
            (OUT / "addendum4_power_partial.json").write_text(json.dumps(rep), encoding="utf-8")
        for h in g.HORIZONS:
            for hit in h2.HITS:
                for n in h2.TARGETS:
                    jobs = [(h, hit, n, 1_600_000_000 + 1_000_000 * h + int(hit * 100) * 10_000 + n + i * 7, "planted") for i in range(POWER_RUNS)]
                    rep["planted"].setdefault(f"h{h}", {})[f"hit{hit:.2f}_n{n}"] = cell_rates(list(pool.map(h2.one_run, jobs, chunksize=20)), rep["offsets"][f"h{h}"])
            print(f"planted h{h} ({time.monotonic() - t0:.0f}s)", flush=True)
            (OUT / "addendum4_power_partial.json").write_text(json.dumps(rep), encoding="utf-8")
    (OUT / "addendum4_power.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return rep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--part", choices=["schedules", "power", "rule"], required=True)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    run_schedules(args.workers) if args.part == "schedules" else run_power(args.workers, rule_only=args.part == "rule")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
