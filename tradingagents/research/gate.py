"""Trade definition, costs, targets, folds and the pass / fail gate (docs/gate_v1.json, docs/PA_39).

Everything is in return terms (share of notional): no lot sizes. Futures only. Pure functions over frames from the
research loader; :func:`load` is the only door to data here. It holds no unlock, so any read of 2025-01-01 onward or of the
forward holdout raises, and the attempt is logged.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binom

from tradingagents.analytics import trial_log
from tradingagents.analytics.costs import DEFAULT_RATES, FUTURES
from tradingagents.research import loader

ROOT = Path(__file__).resolve().parents[2]
GATE_FILE = ROOT / "docs" / "gate_v1.json"
GATE_SHA256 = "48379c7ae307ca8df89ba32998e1e9035fa7960c1e5220a33acb46b3a96dbf28"
HORIZONS = (1, 2, 3, 5, 10)
FOREIGN_INDICES = frozenset({"DJIA", "S&P500", "FTSE100"})
REFERENCE_NOTIONAL = 1_000_000.0          # ASSUMPTION: turns the flat brokerage per order into a share of notional
SLIPPAGE_BPS = {"index": 2.0, "stock": 5.0}   # ASSUMPTION: per fill; no measured historical spread exists
MIN_MOVE_COST_MULTIPLE = 2.0
GATE_COST_MULTIPLE = 1.5
LAST_RESEARCH_DAY = date(2024, 12, 31)
FOLDS = ((2013, 2014), (2015, 2016), (2017, 2018), (2019, 2020), (2021, 2022), (2023, 2024))
BOOTSTRAP_REPS = 2000


# ---------------------------------------------------------------- data door

def load(dataset: str, start: date | None = None, end: date | None = None, symbols=None, root=None,
         log_path=None) -> pd.DataFrame:
    """Base tables through the research loader, no unlocks. A refused read is logged, then re-raised."""
    try:
        return loader.load(dataset, start=start, end=end or LAST_RESEARCH_DAY, symbols=symbols, root=root,
                           log_path=log_path)
    except (loader.HoldoutLocked, loader.LiveTableRefused) as exc:
        trial_log.log_event("holdout_refused", {"dataset": dataset, "start": start, "end": end, "error": str(exc)}, log_path)
        raise


# ---------------------------------------------------------------- costs

def round_trip_cost(kind: str, multiple: float = 1.0, rates=DEFAULT_RATES) -> float:
    """Round-trip cost as a share of notional: the repo's futures rates (cost model unverified) plus slippage."""
    stt = sum(rates.stt[FUTURES])
    exchange, sebi, stamp = 2 * rates.exchange[FUTURES], 2 * rates.sebi_fee, rates.stamp[FUTURES]
    brokerage = 2 * rates.brokerage_flat[FUTURES] / REFERENCE_NOTIONAL
    gst = rates.gst * (brokerage + exchange + sebi)
    return multiple * (stt + exchange + sebi + stamp + brokerage + gst + 2 * SLIPPAGE_BPS[kind] / 1e4)


def _costs(kinds: pd.Series, multiple: float) -> np.ndarray:
    return np.where(kinds == "index", round_trip_cost("index", multiple), round_trip_cost("stock", multiple))


# ---------------------------------------------------------------- sessions, contracts, returns

def min_days_to_expiry(h: int) -> int:
    """A trade's contract must have at least this many calendar days left at the signal, so it outlives the exit."""
    return math.ceil(1.4 * h) + 4


def session_list(futures: pd.DataFrame, holes: Sequence[date] = ()) -> list[date]:
    return sorted(set(pd.to_datetime(futures["trade_date"]).dt.date) | {d for d in holes if d <= max(futures["trade_date"])})


def clean_futures(futures: pd.DataFrame) -> pd.DataFrame:
    f = futures[futures["instrument"].isin(["FUTIDX", "FUTSTK"]) & ~futures["symbol"].isin(FOREIGN_INDICES)].copy()
    f["trade_date"] = pd.to_datetime(f["trade_date"]).dt.date
    f["expiry"] = pd.to_datetime(f["expiry"]).dt.date
    f["kind"] = np.where(f["instrument"] == "FUTIDX", "index", "stock")
    return f.sort_values(["symbol", "expiry", "trade_date"]).reset_index(drop=True)


def split_events(f: pd.DataFrame) -> pd.DataFrame:
    """(symbol, trade_date) where a contract's price and open interest moved inversely by the same factor: the footprint
    of a split or bonus (price / k, open interest x k). Prices are never adjusted; trades spanning one are not taken."""
    g = f.groupby(["symbol", "expiry"], sort=False)
    p = f["close"] / g["close"].shift(1)
    o = f["open_interest"] / g["open_interest"].shift(1)
    big = (p <= 0.8) | (p >= 1.25)
    match = (p * o >= 0.8) & (p * o <= 1.25)
    return f.loc[big & match, ["symbol", "trade_date"]].drop_duplicates().reset_index(drop=True)


def daily_returns(f: pd.DataFrame, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """Close-to-close return per (symbol, session) on one contract only: the nearest at the previous session. A contract
    change is therefore never a return. Sessions with a split or bonus footprint are empty."""
    g = f.groupby(["symbol", "expiry"], sort=False)
    r = f.assign(ret=f["close"] / g["close"].shift(1) - 1, prev=g["trade_date"].shift(1))
    r = r.dropna(subset=["ret", "prev"])
    near = f.groupby(["symbol", "trade_date"])["expiry"].min().rename("near").reset_index().rename(columns={"trade_date": "prev"})
    r = r.merge(near, on=["symbol", "prev"])
    r = r[r["expiry"] == r["near"]]
    out = r[["symbol", "trade_date", "ret"]]
    if events is not None and len(events):
        out = out.merge(events.assign(_e=True), on=["symbol", "trade_date"], how="left")
        out = out[out["_e"].isna()].drop(columns="_e")
    return out.sort_values(["symbol", "trade_date"]).reset_index(drop=True)


def build_trades(f: pd.DataFrame, h: int, sessions: list[date], events: pd.DataFrame | None = None) -> pd.DataFrame:
    """Every possible long trade for horizon ``h``: signal after the close of D, entry at the open of the next session,
    exit at the close of session D + h, one contract throughout, chosen at D from the contracts listed at D."""
    pos = {d: i for i, d in enumerate(sessions)}
    idx = f["trade_date"].map(pos)
    good = idx + h < len(sessions)
    base = f.loc[good, ["symbol", "expiry", "trade_date", "kind"]].rename(columns={"trade_date": "signal"})
    base["entry"] = [sessions[i + 1] for i in idx[good].astype(int)]
    base["exit"] = [sessions[i + h] for i in idx[good].astype(int)]
    days = (pd.to_datetime(base["expiry"]) - pd.to_datetime(base["signal"])).dt.days
    base = base[days >= min_days_to_expiry(h)]
    base = base.sort_values(["symbol", "signal", "expiry"]).drop_duplicates(["symbol", "signal"])      # nearest allowed
    px = f[["symbol", "expiry", "trade_date", "open", "close", "settle", "contracts"]]
    t = base.merge(px.rename(columns={"trade_date": "entry", "open": "e_open", "contracts": "e_contracts"})
                   [["symbol", "expiry", "entry", "e_open", "e_contracts"]], on=["symbol", "expiry", "entry"], how="inner")
    t = t.merge(px.rename(columns={"trade_date": "exit", "close": "x_close", "settle": "x_settle", "contracts": "x_contracts"})
                [["symbol", "expiry", "exit", "x_close", "x_settle", "x_contracts"]], on=["symbol", "expiry", "exit"], how="inner")
    t = t[(t["e_open"] > 0) & (t["e_contracts"] > 0)]
    t["x_price"] = np.where(t["x_contracts"] > 0, t["x_close"], t["x_settle"])       # untraded exit: NSE's settle price
    t = t[t["x_price"] > 0]
    t["gross"] = t["x_price"] / t["e_open"] - 1
    if events is not None and len(events):
        e = events.rename(columns={"trade_date": "event"})
        m = t[["symbol", "entry", "exit"]].drop_duplicates().merge(e, on="symbol")
        hit = m[(m["event"] > m["entry"]) & (m["event"] <= m["exit"])][["symbol", "entry"]].drop_duplicates().assign(_h=True)
        t = t.merge(hit, on=["symbol", "entry"], how="left")
        t = t[t["_h"].isna()].drop(columns="_h")
    return t[["symbol", "kind", "expiry", "signal", "entry", "exit", "e_open", "x_price", "gross"]].reset_index(drop=True)


def attach_membership(trades: pd.DataFrame, membership: pd.DataFrame) -> pd.DataFrame:
    """Keep trades whose symbol is a universe member on the entry session (decided from rows public at that session)."""
    m = membership[["date", "symbol"]].rename(columns={"date": "entry"}).drop_duplicates()
    return trades.merge(m, on=["symbol", "entry"]).reset_index(drop=True)


def one_open_trade(trades: pd.DataFrame) -> pd.DataFrame:
    """Per underlying, oldest first: a signal is taken only if its entry is after the open trade's exit. Signals inside an
    open trade are ignored, never queued."""
    t = trades.sort_values(["symbol", "signal"])
    keep = np.zeros(len(t), dtype=bool)
    last_sym, last_exit = None, None
    for i, (s, en, ex) in enumerate(zip(t["symbol"].to_numpy(), t["entry"].to_numpy(), t["exit"].to_numpy(), strict=True)):
        if s != last_sym or en > last_exit:
            keep[i], last_sym, last_exit = True, s, ex
    return t[keep].reset_index(drop=True)


# ---------------------------------------------------------------- features, targets

def expected_move(returns: pd.DataFrame, h: int, window: int = 20) -> pd.DataFrame:
    """Ex-ante expected |move| over h sessions, known at the close of the signal day: 0.8 x trailing std x sqrt(h)."""
    r = returns.sort_values(["symbol", "trade_date"])
    sd = r.groupby("symbol")["ret"].transform(lambda x: x.rolling(window, min_periods=window).std())
    return pd.DataFrame({"symbol": r["symbol"], "signal": r["trade_date"], "exp_move": 0.8 * sd * math.sqrt(h)}).dropna()


def apply_min_move(trades: pd.DataFrame, exp: pd.DataFrame) -> pd.DataFrame:
    """Skip a trade whose expected |move| is below MIN_MOVE_COST_MULTIPLE x its round-trip cost at the gate's cost level."""
    t = trades.merge(exp, on=["symbol", "signal"], how="inner")
    return t[t["exp_move"] >= MIN_MOVE_COST_MULTIPLE * _costs(t["kind"], GATE_COST_MULTIPLE)].reset_index(drop=True)


def signals_baseline(name: str, trades: pd.DataFrame, returns: pd.DataFrame) -> pd.Series:
    """+1 / -1 / 0 per trade row, from data known at the close of the signal day."""
    if name == "always_long":
        return pd.Series(1, index=trades.index)
    if name == "always_short":
        return pd.Series(-1, index=trades.index)
    r = returns.sort_values(["symbol", "trade_date"]).rename(columns={"trade_date": "signal"})
    if name == "prev_day":
        v = r.assign(v=r["ret"])
    elif name == "momentum_5d":
        v = r.assign(v=r.groupby("symbol")["ret"].transform(lambda x: x.rolling(5, min_periods=5).sum()))
    else:
        raise ValueError(name)
    m = trades[["symbol", "signal"]].merge(v[["symbol", "signal", "v"]], on=["symbol", "signal"], how="left")
    return pd.Series(np.sign(m["v"].fillna(0)).astype(int).to_numpy(), index=trades.index)


def targets(trades: pd.DataFrame, returns: pd.DataFrame, h: int, sessions: list[date], multiple: float = 1.0) -> pd.DataFrame:
    """T1 sign of the net return (per side), T2 net magnitude, T3 forward realized volatility over the trade's h sessions."""
    t = trades.copy()
    c = _costs(t["kind"], multiple)
    t["t2_long"], t["t2_short"] = t["gross"] - c, -t["gross"] - c
    t["t1_long"], t["t1_short"] = t["t2_long"] > 0, t["t2_short"] > 0
    pos = {d: i for i, d in enumerate(sessions)}
    r = returns.assign(i=returns["trade_date"].map(pos))
    grouped = {s: g.set_index("i")["ret"] for s, g in r.groupby("symbol")}
    vols = []
    for s, d in zip(t["symbol"], t["signal"], strict=True):
        i = pos[d]
        g = grouped.get(s)
        w = g.reindex(range(i + 1, i + h + 1)).dropna() if g is not None else pd.Series(dtype=float)
        vols.append(float(np.sqrt((w ** 2).mean())) if len(w) else np.nan)
    t["t3_vol"] = vols
    return t


def net_returns(trades: pd.DataFrame, direction, multiple: float = GATE_COST_MULTIPLE, weight=1.0) -> np.ndarray:
    return (np.asarray(direction) * trades["gross"].to_numpy() - _costs(trades["kind"], multiple)) * np.asarray(weight)


# ---------------------------------------------------------------- statistics

def effective_count(dates: np.ndarray, values: np.ndarray) -> float:
    """Cluster-adjusted count: N / (1 + (m0 - 1) rho), clusters = signal dates, rho = ANOVA intra-date correlation of the
    values, floored at 0. Fewer than two clusters count as one independent trade."""
    n = len(values)
    if n == 0:
        return 0.0
    _, inv, m = np.unique(dates, return_inverse=True, return_counts=True)
    k = len(m)
    if k < 2:
        return 1.0
    sums = np.bincount(inv, values)
    means = sums / m
    grand = values.mean()
    ssb = float((m * (means - grand) ** 2).sum())
    ssw = float(((values - means[inv]) ** 2).sum())
    m0 = (n - (m ** 2).sum() / n) / (k - 1)
    if n == k or m0 <= 1:
        return float(k)
    msb, msw = ssb / (k - 1), ssw / (n - k)
    rho = max(0.0, (msb - msw) / (msb + (m0 - 1) * msw)) if (msb + (m0 - 1) * msw) > 0 else 0.0
    return float(n / (1 + (m0 - 1) * rho))


def block_bootstrap_lower(dates: np.ndarray, values: np.ndarray, block: int, rng, reps: int = BOOTSTRAP_REPS) -> float:
    """Lower bound of the 95% interval of the mean per trade: whole signal dates, moving blocks of ``block`` dates."""
    u, inv = np.unique(dates, return_inverse=True)
    k = len(u)
    if k == 0:
        return float("nan")
    s, c = np.bincount(inv, values), np.bincount(inv)
    if k <= block:
        return float(s.sum() / c.sum())
    blocks = math.ceil(k / block)
    starts = rng.integers(0, k - block + 1, size=(reps, blocks))
    picks = (starts[:, :, None] + np.arange(block)).reshape(reps, -1)[:, :k]
    return float(np.percentile(s[picks].sum(axis=1) / c[picks].sum(axis=1), 2.5))


def fold_of(entry: pd.Series, folds=FOLDS) -> np.ndarray:
    y = pd.to_datetime(entry).dt.year.to_numpy()
    out = np.full(len(y), -1)
    for i, (a, b) in enumerate(folds):
        out[(y >= a) & (y <= b)] = i
    return out


def train_mask(entry: pd.Series, exit_: pd.Series, fold: int, h: int, sessions: list[date], folds=FOLDS) -> np.ndarray:
    """Expanding-window training rows for a test fold: everything before it, less the purge (trades exiting within h sessions
    of the test start) and less the embargo (entries within h sessions after any earlier test fold)."""
    pos = {d: i for i, d in enumerate(sessions)}
    def first_in(y):
        return next((i for i, d in enumerate(sessions) if d.year >= y), len(sessions))
    start = first_in(folds[fold][0])
    e, x = entry.map(pos).to_numpy(), exit_.map(pos).to_numpy()
    keep = x < start - h
    for a, b in folds[:fold]:
        s, f = first_in(a), first_in(b + 1)
        keep &= ~((e >= s) & (e < f + h))           # earlier test folds stay usable only outside their embargo
    return keep


# ---------------------------------------------------------------- the gate

def x_limit(h: int, spec: dict | None = None) -> float:
    return (spec or read_spec())["gate"]["g"]["x_h_percent"][str(h)] / 100.0


def read_spec(path: Path | None = None) -> dict:
    """The frozen gate; refused if its canonical hash changed (a change is a new version and a logged trial)."""
    spec = json.loads((path or GATE_FILE).read_text(encoding="utf-8"))
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != GATE_SHA256:
        raise ValueError("gate_v1.json changed after it was frozen")
    return spec


def evaluate(forward: dict, walk_forward: dict, baselines: dict[str, float], u2_expectancy: float, h: int, x: float,
             rng, reps: int = BOOTSTRAP_REPS, min_trades: int = 100) -> dict:
    """All gate items. ``forward``: date, net (at 1.5x), win_null (per-trade win rate of the same structure with a random
    direction). ``walk_forward``: fold, date, net, from the same model at 1.5x. Returns each item and ``passed``."""
    d, net = np.asarray(forward["date"]), np.asarray(forward["net"], dtype=float)
    n_raw = len(net)
    n_eff = effective_count(d, net)
    wins = net > 0
    wr = float(wins.mean()) if n_raw else float("nan")
    exp = float(net.mean()) if n_raw else float("nan")
    p0 = float(np.mean(forward["win_null"])) if n_raw else float("nan")
    k_eff, n_int = int(round(wr * n_eff)) if n_raw else 0, int(round(n_eff))
    p_binom = float(binom.sf(k_eff - 1, n_int, p0)) if n_int else 1.0
    lower = block_bootstrap_lower(d, net, h, rng, reps) if n_raw else float("nan")
    fold, wf_d, wf_net = (np.asarray(walk_forward[k]) for k in ("fold", "date", "net"))
    folds = sorted(set(fold[fold >= 0].tolist())) if len(fold) else []
    means = [float(wf_net[fold == i].mean()) for i in folds]
    effs = [effective_count(wf_d[fold == i], wf_net[fold == i]) for i in folds]
    expected_folds = walk_forward.get("n_folds", len(FOLDS))
    share = (sum(m > 0 for m in means) / expected_folds) if expected_folds else 0.0
    items = {
        "a": {"pass": n_eff >= min_trades, "raw": n_raw, "effective": n_eff},
        "b": {"pass": bool(wr >= 0.60), "win_rate": wr},
        "c": {"pass": bool(p_binom < 0.05), "p": p_binom, "null_win_rate": p0},
        "d": {"pass": bool(exp > 0 and lower > 0), "expectancy": exp, "lower": lower},
        "e": {"pass": bool(baselines) and all(exp > v for v in baselines.values()), "baselines": baselines},
        "f": {"pass": bool(np.sign(u2_expectancy) == np.sign(exp) and exp != 0), "u2_expectancy": u2_expectancy},
        "g": {"pass": bool(share >= 0.70 and len(means) == expected_folds and all(m >= -x for m in means)
                           and all(e >= 100 for e in effs)),
              "share_positive": share, "worst_fold": min(means) if means else float("nan"),
              "min_effective": min(effs) if effs else 0.0},
    }
    items["passed"] = all(items[k]["pass"] for k in "abcdefg")
    return items
