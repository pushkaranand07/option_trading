"""Power for the AI strategist's forward test (docs/ai_strategist_test_v1.json, docs/PA_49). No LLM; no model; development data only.

    python scripts/research_ai_test_power.py

NIFTY weekly options, 2019-2022: for each session and each direction, three defined-risk structures held to expiry, net of charges, as a
share of max risk. A trade's return is one structure in a random direction, plus a planted edge. Resampled by expiry week, as in gate v2.
Pass, as written in the spec: mean above 0 with the 2.5th percentile bootstrap bound above 0, and mean above the 97.5th percentile of
random-direction draws on the same sessions. Closing prices stand in for bid and ask. Writes reports/ai_test/power.json.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.analytics import costs  # noqa: E402
from tradingagents.research import gate as g, loader  # noqa: E402

LOT = 50
EDGES = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30)
COUNTS = (50, 100, 150, 200, 300, 400, 500, 750, 1000, 1500, 2000)
RUNS, BOOT, RANDOM_DRAWS = 1000, 400, 200
OUT = ROOT / "reports" / "ai_test"


def nearest(strikes: np.ndarray, x: float) -> float:
    return float(strikes[np.argmin(np.abs(strikes - x))])


def value(legs: list[tuple[int, str, float, float]], spot: float) -> float:
    """Value per unit at expiry of (+1 buy / -1 sell, type, strike, entry)."""
    return sum(s * (max(spot - k, 0.0) if t == "CE" else max(k - spot, 0.0)) for s, t, k, _ in legs)


def outcome(legs: list[tuple[int, str, float, float]], spot_end: float, *_) -> float | None:
    net_entry = sum(s * e for s, _t, _k, e in legs)
    points = value(legs, spot_end) - net_entry
    wings = [k for s, t, k, e in legs]
    width = 0.0
    for typ in ("CE", "PE"):
        ks = sorted(k for s, t, k, _e in legs if t == typ)
        if len(ks) == 2:
            width = max(width, ks[1] - ks[0])
    risk = net_entry if net_entry > 0 else width + net_entry      # debit paid, or width less credit
    if not wings or risk <= 0:
        return None
    charges = sum(costs.fill_charges(costs.OPTIONS, LOT, e, "buy" if s > 0 else "sell") + costs.fill_charges(costs.OPTIONS, LOT, e, "sell" if s > 0 else "buy") for s, _t, _k, e in legs)
    return (points * LOT - charges) / (risk * LOT)


def structures(sign: int, spot: float, strikes: np.ndarray) -> dict[str, list[tuple[int, str, float]]]:
    atm = nearest(strikes, spot)
    step = nearest(strikes, spot * 1.02) - atm
    t = "CE" if sign > 0 else "PE"
    far = nearest(strikes, atm + sign * step)
    centre = nearest(strikes, spot * (1 + sign * 0.01))
    w1, w2 = spot * 0.02, spot * 0.03
    return {"long_option": [(1, t, atm)], "debit_spread": [(1, t, atm), (-1, t, far)],
            "iron_condor": [(1, "PE", nearest(strikes, centre - w2)), (-1, "PE", nearest(strikes, centre - w1)), (-1, "CE", nearest(strikes, centre + w1)), (1, "CE", nearest(strikes, centre + w2))]}


def build_pool() -> pd.DataFrame:
    end = date(2022, 12, 31)
    chain = g.load("base_option_chain", start=date(2019, 3, 1), end=end, symbols=["NIFTY"])
    chain = loader.european_only(chain)
    index = g.load("base_index", start=date(2019, 3, 1), end=end, symbols=["NIFTY"])
    closes = dict(zip(pd.to_datetime(index["trade_date"]), index["close"], strict=True))
    chain = chain.assign(d=pd.to_datetime(chain["trade_date"]), x=pd.to_datetime(chain["expiry"]))
    chain = chain[(chain["contracts"] > 0) & (chain["close"] > 0)]
    rows = []
    for day, part in chain.groupby("d"):
        spot = closes.get(day)
        ahead = sorted(part.loc[part["x"] > day, "x"].unique())
        if spot is None or not ahead:
            continue
        expiry = pd.Timestamp(ahead[0])
        spot_end = closes.get(expiry)
        one = part[part["x"] == expiry]
        if spot_end is None or len(one) < 8:
            continue
        price = {(r.option_type, float(r.strike)): float(r.close) for r in one.itertuples()}
        strikes = np.array(sorted({k for _t, k in price}))
        for sign in (1, -1):
            for name, legs in structures(sign, spot, strikes).items():
                if not all((t, k) in price for _s, t, k in legs):
                    continue
                r = outcome([(s, t, k, price[(t, k)]) for s, t, k in legs], spot_end)
                if r is not None:
                    rows.append({"date": day, "expiry": expiry, "sign": sign, "structure": name, "ret": r})
    return pd.DataFrame(rows)


def simulate(pool: pd.DataFrame, n: int, edge: float, rng) -> tuple[float, float]:
    """Share of runs passing, and share passing on the mean and bound alone."""
    both = pool.pivot_table(index=["date", "expiry", "structure"], columns="sign", values="ret").dropna().reset_index()
    up, down = both[1].to_numpy(), both[-1].to_numpy()
    weeks = both["expiry"].to_numpy()
    u_weeks = np.unique(weeks)
    index_by_week = {w: np.flatnonzero(weeks == w) for w in u_weeks}
    per_week = max(1, round(np.mean([len(np.unique(both.loc[i, "date"])) for i in index_by_week.values()])))
    n_weeks = max(2, int(np.ceil(n / per_week)))
    passed, bound = 0, 0
    for _ in range(RUNS):
        chosen = rng.choice(u_weeks, size=n_weeks)
        idx = np.concatenate([rng.choice(index_by_week[w], size=per_week) for w in chosen])[:n]
        labels = np.repeat(np.arange(n_weeks), per_week)[:n]
        coin = rng.random(len(idx)) < 0.5
        r = np.where(coin, up[idx], down[idx]) + edge
        mean = r.mean()
        s = np.bincount(labels, r)
        c = np.bincount(labels)
        draws = rng.integers(0, n_weeks, size=(BOOT, n_weeks))
        boot = s[draws].sum(axis=1) / c[draws].sum(axis=1)
        low = np.percentile(boot, 2.5)
        coins = rng.random((RANDOM_DRAWS, len(idx))) < 0.5
        random_means = np.where(coins, up[idx], down[idx]).mean(axis=1)
        ok = mean > 0 and low > 0
        bound += ok
        passed += ok and mean > np.percentile(random_means, 97.5)
    return passed / RUNS, bound / RUNS


def main() -> int:
    pool = build_pool()
    rng = np.random.default_rng(49)
    rep: dict = {"label": "NIFTY weekly options 2019-2022, closing prices, one lot of 50 for charges, hold to expiry; cost model unverified", "rows": len(pool), "sessions": int(pool["date"].nunique()), "expiries": int(pool["expiry"].nunique()),
                 "first": str(pool["date"].min().date()), "last": str(pool["date"].max().date()), "runs_per_cell": RUNS,
                 "by_structure": {k: {"rows": len(v), "sd_of_return": float(v["ret"].std()), "mean_random_direction": float(v["ret"].mean())} for k, v in pool.groupby("structure")}, "cells": {}}
    print({k: rep[k] for k in ("rows", "sessions", "expiries", "first", "last")}, rep["by_structure"], flush=True)
    for edge in EDGES:
        for n in COUNTS:
            p, b = simulate(pool, n, edge, rng)
            rep["cells"].setdefault(f"{edge:.2f}", {})[str(n)] = {"pass": p, "mean_and_bound_only": b}
        print(edge, {k: round(v["pass"], 3) for k, v in rep["cells"][f"{edge:.2f}"].items()}, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "power.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
