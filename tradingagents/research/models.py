"""Model suite v1 under the frozen gate: fits, predictions, acting rules, gate items (docs/models_v1.json, docs/PA_47).

Fit on U1 rows before each test fold, less a purge; applied to U1 and U2 rows of the fold. Features for signal D read D-1
(features_v1). Winsor limits, scaling and calibration come from training rows only. An LLM is not a model or feature source here.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binom
from sklearn.linear_model import LogisticRegression, SGDClassifier, SGDRegressor

from tradingagents.research import features as fx, gate as g, gate2 as g2

SPEC_FILE = g.ROOT / "docs" / "models_v1.json"
SPEC_SHA256 = "2f2484efa543a3c9e2c5567747342b23f6eb32df26ff5dc8682e55907280ff78"
DEV_FOLDS = (0, 1, 2, 3, 4)
VALIDATION_FOLD = 5
ITEM_D_PERCENTILE = 2.5 / 3
UNCLIPPED = ("rank_", "day_of_week", "days_", "expiry_week", "board_", "results_", "nifty_above", "n_liquid")
SEQ = 10


def read_spec(path: Path | None = None) -> dict:
    spec = json.loads((path or SPEC_FILE).read_text(encoding="utf-8"))
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != SPEC_SHA256:
        raise ValueError("models_v1.json changed after it was frozen")
    return spec


# ---------------------------------------------------------------- folds

def fit_mask(entry: np.ndarray, exit_: np.ndarray, fold: int, h: int, sessions: list, folds=g.FOLDS) -> np.ndarray:
    """Training rows for a test fold. ``entry`` and ``exit_`` are session positions. Everything ending more than h sessions
    before the fold, less entries within h sessions after each earlier test fold. Earlier folds' rows are history, so they stay."""
    def first_in(y: int) -> int:
        return next((i for i, d in enumerate(sessions) if d.year >= y), len(sessions))

    keep = exit_ < first_in(folds[fold][0]) - h
    for _a, b in folds[:fold]:
        end = first_in(b + 1)
        keep &= ~((entry >= end) & (entry < end + h))
    return keep


def allowed_columns(features: list[str], fold: int, allowed: dict[str, list[str]], folds=g.FOLDS) -> list[str]:
    """This fold's features from addendum 3, which fixes them in advance."""
    a, b = folds[fold]
    names = set(allowed[f"{a}-{b}"])
    return [c for c in features if c in names]


def inner_split(signal_pos: np.ndarray, exit_pos: np.ndarray, h: int, share: float = 0.20) -> tuple[np.ndarray, np.ndarray]:
    """(fit rows, holdout rows): the holdout is the last share of signal dates; fit rows end more than h sessions before it."""
    days = np.unique(signal_pos)
    start = days[int(len(days) * (1 - share))]
    return exit_pos < start - h, signal_pos >= start


# ---------------------------------------------------------------- preparation

class Prep:
    """Winsor limits and scaling from training rows only. Missing stays missing here; ``matrix`` adds zeros and group flags."""

    def __init__(self, train: pd.DataFrame, columns: list[str], groups: dict[str, list[str]]):
        self.columns, self.groups = columns, {k: [c for c in v if c in columns] for k, v in groups.items()}
        self.limits = {c: fx.fit_limits(train[c]) for c in columns if not c.startswith(UNCLIPPED)}
        v = self.clip(train)
        self.mean, self.std = v.mean(axis=0).to_numpy(dtype=np.float64), v.std(axis=0).to_numpy(dtype=np.float64)
        self.mean = np.nan_to_num(self.mean)
        self.std = np.where(np.isfinite(self.std) & (self.std > 0), self.std, 1.0)

    def clip(self, frame: pd.DataFrame) -> pd.DataFrame:
        return fx.apply_limits(frame[self.columns], self.limits)

    def matrix(self, frame: pd.DataFrame) -> np.ndarray:
        raw = self.clip(frame).to_numpy(dtype=np.float32)
        flags = [np.isnan(raw[:, [self.columns.index(c) for c in cols]]).any(axis=1) for cols in self.groups.values() if cols]
        scaled = np.nan_to_num((raw - self.mean) / self.std, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
        return np.column_stack([scaled, *[f.astype(np.float32) for f in flags]]) if flags else scaled


# ---------------------------------------------------------------- learners: each returns a function from a frame to predictions

def fit_sgd_logistic(train, y, prep, params, seed, **_):
    m = SGDClassifier(loss="log_loss", penalty="elasticnet", alpha=params["alpha"], l1_ratio=params["l1_ratio"], max_iter=5, tol=None, random_state=seed)
    m.fit(prep.matrix(train), y.astype(int))
    return lambda frame: m.predict_proba(prep.matrix(frame))[:, 1]


def fit_sgd_linear(train, y, prep, params, seed, **_):
    lo, hi = fx.fit_limits(pd.Series(y))
    scale = float(np.nanstd(np.clip(y, lo, hi))) or 1.0
    m = SGDRegressor(loss="squared_error", penalty="elasticnet", alpha=params["alpha"], l1_ratio=params["l1_ratio"], max_iter=5, tol=None, random_state=seed)
    m.fit(prep.matrix(train), np.clip(y, lo, hi) / scale)
    return lambda frame: m.predict(prep.matrix(frame)) * scale


def _lgbm(params: dict, seed: int, classifier: bool, columns: list[str], monotone: dict | None, threads: int):
    import lightgbm as lgb

    depth = params["max_depth"]
    kw = {"n_estimators": 200, "learning_rate": 0.05, "max_depth": depth, "num_leaves": min(2 ** depth - 1, 15), "min_child_samples": 500, "colsample_bytree": 0.5,
          "subsample": 0.5, "subsample_freq": 1, "reg_lambda": 10.0, "random_state": seed, "n_jobs": threads, "verbose": -1}
    if monotone:
        kw["monotone_constraints"] = [monotone["constraint"] if c in monotone["features"] else 0 for c in columns]
    return lgb.LGBMClassifier(**kw) if classifier else lgb.LGBMRegressor(**kw)


def fit_lgbm_classifier(train, y, prep, params, seed, monotone=None, threads=2, **_):
    m = _lgbm(params, seed, True, prep.columns, monotone, threads)
    m.fit(prep.clip(train).to_numpy(dtype=np.float32), y.astype(int))
    fit = lambda frame: m.predict_proba(prep.clip(frame).to_numpy(dtype=np.float32))[:, 1]  # noqa: E731
    fit.model = m
    return fit


def fit_lgbm_regressor(train, y, prep, params, seed, threads=2, **_):
    m = _lgbm(params, seed, False, prep.columns, None, threads)
    m.fit(prep.clip(train).to_numpy(dtype=np.float32), y)
    return lambda frame: m.predict(prep.clip(frame).to_numpy(dtype=np.float32))


def sequence_index(symbol_ids: np.ndarray, session_pos: np.ndarray, length: int = SEQ) -> np.ndarray:
    """For each panel row, the panel rows of the same symbol on this and the previous sessions, oldest first; -1 where none.
    It only ever looks back."""
    key = symbol_ids.astype(np.int64) * 1_000_000 + session_pos.astype(np.int64)
    order = np.argsort(key)
    sorted_key = key[order]
    out = np.full((len(key), length), -1, dtype=np.int64)
    for k in range(length):
        want = key - (length - 1 - k)
        at = np.searchsorted(sorted_key, want).clip(max=len(key) - 1)
        hit = sorted_key[at] == want
        out[hit, k] = order[at[hit]]
    return out


def fit_tcn(train, y, prep, params, seed, panel=None, threads=2, **_):
    """``panel``: dict with ``frame`` (one row per signal date and symbol, in panel order) and ``seq`` (sequence_index)."""
    import torch
    from torch import nn

    torch.set_num_threads(threads)
    torch.manual_seed(seed)
    channels = params["channels"]
    # everything is scaled with training-row statistics; rows for later dates are only read when predicting them
    grid = prep.matrix(panel["frame"])
    empty = np.zeros((1, grid.shape[1]), dtype=np.float32)
    empty[0, len(prep.columns):] = 1.0
    grid = torch.from_numpy(np.vstack([grid, empty]))
    seq = torch.from_numpy(np.where(panel["seq"] < 0, len(grid) - 1, panel["seq"]))
    net = nn.Sequential(nn.Conv1d(grid.shape[1], channels, 3, dilation=1), nn.ReLU(), nn.Dropout(0.2), nn.Conv1d(channels, channels, 3, dilation=2), nn.ReLU(), nn.Dropout(0.2))
    head = nn.Linear(channels, 1)
    optimizer = torch.optim.Adam([*net.parameters(), *head.parameters()], lr=0.001, weight_decay=0.0001)
    loss_fn = nn.BCEWithLogitsLoss()

    def forward(rows):
        return head(net(grid[seq[rows]].transpose(1, 2))[:, :, -1]).squeeze(1)

    rows = torch.from_numpy(train["panel_row"].to_numpy(dtype=np.int64))
    target = torch.from_numpy(y.astype(np.float32))
    rng = torch.Generator().manual_seed(seed)
    net.train()
    for _ in range(4):
        order = torch.randperm(len(rows), generator=rng)
        for i in range(0, len(rows), 1024):
            batch = order[i:i + 1024]
            optimizer.zero_grad()
            loss_fn(forward(rows[batch]), target[batch]).backward()
            optimizer.step()
    net.eval()

    def predict(frame):
        out = []
        idx = torch.from_numpy(frame["panel_row"].to_numpy(dtype=np.int64))
        with torch.no_grad():
            for i in range(0, len(idx), 8192):
                out.append(torch.sigmoid(forward(idx[i:i + 8192])).numpy())
        return np.concatenate(out) if out else np.array([])

    return predict


# ---------------------------------------------------------------- acting

def platt(holdout_p: np.ndarray, holdout_y: np.ndarray):
    """A calibrator from the inner holdout. One class in the holdout: no calibration is possible, so the raw value stays."""
    p = np.clip(holdout_p, 1e-6, 1 - 1e-6)
    if len(np.unique(holdout_y)) < 2:
        return lambda x: x
    m = LogisticRegression(C=1e6, max_iter=200).fit(np.log(p / (1 - p)).reshape(-1, 1), holdout_y.astype(int))

    def apply(x):
        x = np.clip(x, 1e-6, 1 - 1e-6)
        return m.predict_proba(np.log(x / (1 - x)).reshape(-1, 1))[:, 1]

    return apply


def act_probability(p: np.ndarray, band: float) -> np.ndarray:
    return np.where(p > 0.5 + band, 1, np.where(p < 0.5 - band, -1, 0))


def act_magnitude(pred: np.ndarray, cost: np.ndarray, multiple: float) -> np.ndarray:
    return np.where(pred > multiple * cost, 1, np.where(pred < -multiple * cost, -1, 0))


def act_rank(frame: pd.DataFrame, score: np.ndarray, bucket: float, stocks: np.ndarray, minimum: int = 20) -> np.ndarray:
    """Per signal date, among stocks with a score: long the top bucket, short the bottom. Fewer than ``minimum``: no trade."""
    x = pd.DataFrame({"d": frame["signal"].to_numpy(), "s": np.where(stocks, score, np.nan)})
    by = x.groupby("d")["s"]
    n = by.transform("count").to_numpy()
    r = by.rank(pct=True).to_numpy()
    out = np.where(r > 1 - bucket, 1, np.where(r <= bucket, -1, 0))
    return np.where((n >= minimum) & np.isfinite(r), out, 0)


def take_trades(frame: pd.DataFrame, direction: np.ndarray) -> pd.DataFrame:
    """The one-open rule over rows with a direction, with net return at the gate's costs."""
    t = frame.assign(_d=direction)
    t = g.one_open_trade(t[t["_d"] != 0])
    return t.assign(net=t["_d"].to_numpy() * t["gross"].to_numpy() - t["cost"].to_numpy())


def best_setting(by_fold: list[dict], minimum_dates: int = 50):
    """The median across folds of each holdout's best setting by net expectancy, with at least ``minimum_dates`` dates. None if no fold has one."""
    picks = []
    for scores in by_fold:
        ok = {k: v["net"] for k, v in scores.items() if v["dates"] >= minimum_dates}
        if ok:
            picks.append(max(ok, key=ok.get))
    return statistics.median_low(picks) if picks else None


# ---------------------------------------------------------------- gate items

def development_items(u1: pd.DataFrame, u2_net: float, h: int, x: float, block: int, rng, percentile: float = ITEM_D_PERCENTILE, folds=DEV_FOLDS, baselines: dict | None = None, baseline_can_fail: bool = False) -> dict:
    """Items a, d, e, f, g on pooled test folds. Item e is computed always and only decides when ``baseline_can_fail``."""
    d, net = u1["signal"].astype(str).to_numpy(), u1["net"].to_numpy(dtype=float)
    n = len(net)
    dates = len(np.unique(d))
    exp = float(net.mean()) if n else float("nan")
    lower = g2.bootstrap_lowers(d, net, block, rng, {"p": percentile})["p"] if n else float("nan")
    means, counts = [], []
    for f in folds:
        part = u1[u1["fold"] == f]
        means.append(float(part["net"].mean()) if len(part) else float("nan"))
        counts.append(int(part["signal"].nunique()))
    finite = [m for m in means if np.isfinite(m)]
    share = sum(m > 0 for m in finite) / len(folds)
    win = float((net > 0).mean()) if n else float("nan")
    p0 = float(u1["win_null"].mean()) if n else float("nan")
    k = round(win * dates) if n else 0
    upper = None if not baselines else {b: float(max(v)) for b, v in baselines.items()}
    e_pass = bool(baselines) and g2.beats_upper_range(exp * 100, baselines)
    items = {
        "a": {"pass": dates >= g2.MIN_DATES, "raw": n, "distinct_dates": dates},
        "d": {"pass": bool(n and exp > 0 and lower > 0), "expectancy_pct": exp * 100, "lower_pct": lower * 100 if n else float("nan"), "percentile": percentile},
        "e": {"pass": e_pass, "can_fail": baseline_can_fail, "upper_pct": upper},
        "f": {"pass": bool(n and np.isfinite(u2_net) and np.sign(u2_net) == np.sign(exp) and exp != 0), "u2_expectancy_pct": u2_net * 100},
        "g": {"pass": bool(len(finite) == len(folds) and share >= 0.70 and min(finite) >= -x and min(counts) >= g2.MIN_DATES), "share_positive": share, "fold_means_pct": [m * 100 for m in means], "fold_dates": counts, "worst_allowed_pct": -x * 100},
        "b_report": {"win_rate": win},
        "c_report": {"p": float(binom.sf(k - 1, dates, p0)) if dates else 1.0, "null_win": p0},
    }
    needed = "adfg" + ("e" if baseline_can_fail else "")
    items["pass"] = all(items[i]["pass"] for i in needed)
    return items


def drawdown(net: pd.Series, dates: pd.Series) -> float:
    """Worst peak-to-trough of the running sum of each date's mean net return, in percent of notional per date."""
    daily = net.groupby(pd.to_datetime(dates)).mean().sort_index()
    curve = daily.cumsum()
    return float((curve - curve.cummax()).min() * 100) if len(curve) else float("nan")
