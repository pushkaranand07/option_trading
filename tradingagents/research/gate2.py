"""Gate v2: the action-list skip rule, distinct-date counts, two tiers, calibrated item d (docs/gate_v2.json, docs/PA_40).

Gate v1 (``gate.py``, ``docs/gate_v1.json``) stays on file unchanged. Trade construction, costs and statistics are reused
from it. The skip rule here uses only NSE's corporate-action list; the price / open-interest detector is a diagnostic.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binom

from tradingagents.research import gate as g

GATE_FILE = g.ROOT / "docs" / "gate_v2.json"
GATE_SHA256 = "ecd52239077f0543700b236bf7a9ecee37c0187d4ded2adf60745458c22dfc59"
MIN_DATES, TARGET_DATES = 100, 150


def read_spec(path: Path | None = None) -> dict:
    spec = json.loads((path or GATE_FILE).read_text(encoding="utf-8"))
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != GATE_SHA256:
        raise ValueError("gate_v2.json changed after it was frozen")
    return spec


def action_events(actions: pd.DataFrame) -> pd.DataFrame:
    """(symbol, trade_date) of listed actions, in the shape the trade builder and daily returns take."""
    return actions.rename(columns={"ex_date": "trade_date"})[["symbol", "trade_date"]].drop_duplicates().reset_index(drop=True)


def label_action_list(trades: pd.DataFrame, months: set[str]) -> pd.DataFrame:
    """``has_action_list``: every calendar month from entry to exit has a stored action file. Otherwise the trade is
    labelled "no action list": an action inside it could not have been seen."""
    t = trades.copy()
    e, x = pd.to_datetime(t["entry"]), pd.to_datetime(t["exit"])
    first, last = e.dt.strftime("%Y-%m"), x.dt.strftime("%Y-%m")
    same = first == last
    t["has_action_list"] = first.isin(months) & (same | last.isin(months))
    return t


def prepare(f: pd.DataFrame, actions: pd.DataFrame, rule: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(skip events, daily returns) under a rule: ``A`` action list only (the gate), ``B`` action list plus detector
    (report only)."""
    ev = action_events(actions)
    if rule == "B":
        ev = pd.concat([ev, g.split_events(f)], ignore_index=True).drop_duplicates()
    elif rule != "A":
        raise ValueError(rule)
    return ev, g.daily_returns(f, ev)


def winsorized_mean(values: np.ndarray, pct: float = 0.01) -> float:
    """Report only: the mean with each tail clipped at the 1st and 99th percentiles."""
    if not len(values):
        return float("nan")
    lo, hi = np.percentile(values, [100 * pct, 100 * (1 - pct)])
    return float(np.clip(values, lo, hi).mean())


def evaluate(forward: dict, walk_forward: dict, baselines: dict[str, float], u2_expectancy: float, h: int, x: float, block: int,
             rng, reps: int = g.BOOTSTRAP_REPS) -> dict:
    """Every item, then Tier 1 (a, c, d, e, f, g) and Tier 2 (Tier 1 plus b). Effective trades = distinct signal dates."""
    d, net = np.asarray(forward["date"]), np.asarray(forward["net"], dtype=float)
    n_raw, n_dates = len(net), len(np.unique(d))
    wr = float((net > 0).mean()) if n_raw else float("nan")
    exp = float(net.mean()) if n_raw else float("nan")
    p0 = float(np.mean(forward["win_null"])) if n_raw else float("nan")
    k = int(round(wr * n_dates)) if n_raw else 0
    p_binom = float(binom.sf(k - 1, n_dates, p0)) if n_dates else 1.0
    lower = g.block_bootstrap_lower(d, net, block, rng, reps) if n_raw else float("nan")
    fold, wf_d, wf_net = (np.asarray(walk_forward[c]) for c in ("fold", "date", "net"))
    folds = sorted(set(fold[fold >= 0].tolist())) if len(fold) else []
    means = [float(wf_net[fold == i].mean()) for i in folds]
    dates = [len(np.unique(wf_d[fold == i])) for i in folds]
    expected = walk_forward.get("n_folds", len(g.FOLDS))
    share = sum(m > 0 for m in means) / expected if expected else 0.0
    items = {
        "a": {"pass": n_dates >= MIN_DATES, "raw": n_raw, "distinct_dates": n_dates},
        "b": {"pass": bool(wr >= 0.60), "win_rate": wr},
        "c": {"pass": bool(p_binom < 0.05), "p": p_binom, "null_win_rate": p0},
        "d": {"pass": bool(exp > 0 and lower > 0), "expectancy": exp, "lower": lower},
        "e": {"pass": bool(baselines) and all(exp > v for v in baselines.values()), "baselines": baselines},
        "f": {"pass": bool(np.sign(u2_expectancy) == np.sign(exp) and exp != 0), "u2_expectancy": u2_expectancy},
        "g": {"pass": bool(share >= 0.70 and len(means) == expected and all(m >= -x for m in means) and all(n >= MIN_DATES for n in dates)),
              "share_positive": share, "worst_fold": min(means) if means else float("nan"), "min_fold_dates": min(dates) if dates else 0},
    }
    items["tier1"] = all(items[i]["pass"] for i in "acdefg")
    items["tier2"] = items["tier1"] and items["b"]["pass"]
    return items


def binomial_requirement(p0: float, alpha: float, n: int) -> int:
    """Fewest wins out of n with one-sided exact binomial p < alpha against p0; n + 1 if none."""
    for k in range(n + 1):
        if binom.sf(k - 1, n, p0) < alpha:
            return k
    return n + 1


def binomial_trades_needed(p0: float, alpha: float, win_rate: float, limit: int = 5000) -> int | None:
    """Fewest trades at which ``win_rate`` reaches p < alpha; None if not within ``limit``."""
    for n in range(10, limit + 1):
        if binom.sf(int(round(win_rate * n)) - 1, n, p0) < alpha:
            return n
    return None
