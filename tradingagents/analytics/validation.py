"""Backtest validation that resists overfitting.

Try enough strategies and parameters on the same history and one will look
brilliant by luck alone: ~40 option structures × ~100 entry signals × parameter
grids × investor scorecards is thousands of trials. The best in-sample Sharpe of
1,000 random strategies is high even when none has an edge.

Three defences, used together:

1. Walk-forward: parameters are chosen on a training window and judged only on
   the following, unseen window (with an optional embargo gap), rolling forward.
   Only out-of-sample returns are reported as performance.
2. Deflated Sharpe Ratio (Bailey & López de Prado, 2014): the probability the
   true Sharpe beats the best Sharpe expected from N trials of pure noise,
   adjusted for skew, fat tails and sample length.
3. A minimum trade count: below it, no verdict but "insufficient evidence".

Uses only the standard library's ``NormalDist`` (no SciPy dependency).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()

MIN_TRADES = 30
DSR_SIGNIFICANT = 0.95


@dataclass(frozen=True)
class Split:
    train: pd.Index
    test: pd.Index


def walk_forward_splits(index: pd.Index, train: int, test: int, step: int | None = None,
                        embargo: int = 0) -> list[Split]:
    """Rolling (train, test) windows by position. ``embargo`` bars separate them, so
    signals whose lookback straddles the boundary cannot leak training data into the test."""
    step = step or test
    splits, start = [], 0
    while start + train + embargo + test <= len(index):
        tr = index[start: start + train]
        te = index[start + train + embargo: start + train + embargo + test]
        splits.append(Split(tr, te))
        start += step
    return splits


def sharpe(returns: Iterable[float], periods: int = 252) -> float:
    r = np.asarray(list(returns), dtype=float)
    r = r[~np.isnan(r)]
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods))


def probabilistic_sharpe_ratio(returns: Iterable[float], benchmark_sr: float = 0.0) -> float:
    """P(true per-period Sharpe > ``benchmark_sr``) given sample length, skew and kurtosis."""
    r = np.asarray(list(returns), dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    z = (r - r.mean()) / r.std(ddof=0)
    skew = float((z ** 3).mean())
    kurt = float((z ** 4).mean())          # non-excess; 3 for a normal distribution
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return 0.0
    return _N.cdf((sr - benchmark_sr) * math.sqrt(n - 1) / math.sqrt(denom))


def expected_max_sharpe(n_trials: int, sr_variance: float) -> float:
    """Expected maximum per-period Sharpe among ``n_trials`` skill-less strategies."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    return math.sqrt(sr_variance) * (
        (1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
        + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e))
    )


def deflated_sharpe_ratio(returns: Iterable[float], n_trials: int, trial_sharpes: Iterable[float] | None = None,
                          sr_variance: float | None = None) -> float:
    """PSR against the best Sharpe luck would produce over ``n_trials``.

    The spread of per-period Sharpes across the trials sets how high luck
    reaches; pass ``trial_sharpes`` (per-period, one per trial) or ``sr_variance``.
    """
    if sr_variance is None:
        values = np.asarray(list(trial_sharpes or []), dtype=float)
        sr_variance = float(values.var(ddof=1)) if len(values) > 1 else 0.0
    return probabilistic_sharpe_ratio(returns, expected_max_sharpe(n_trials, sr_variance))


def evidence_verdict(n_trades: int, dsr: float, min_trades: int = MIN_TRADES,
                     threshold: float = DSR_SIGNIFICANT) -> str:
    if n_trades < min_trades:
        return "insufficient_evidence"
    return "significant" if dsr >= threshold else "not_significant"


@dataclass
class FoldResult:
    params: dict
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WalkForwardResult:
    folds: list[FoldResult]
    oos_returns: pd.Series
    n_trials: int
    n_trades: int
    in_sample_sharpe: float
    oos_sharpe: float
    deflated_sharpe: float
    verdict: str
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        decay = self.in_sample_sharpe - self.oos_sharpe
        return (f"walk-forward: {len(self.folds)} folds, {self.n_trials} trials/fold, {self.n_trades} trades | "
                f"Sharpe IS {self.in_sample_sharpe:.2f} -> OOS {self.oos_sharpe:.2f} (decay {decay:+.2f}) | "
                f"DSR {self.deflated_sharpe:.2f} | verdict: {self.verdict}")


def walk_forward(
    data: pd.DataFrame,
    strategy: Callable[[pd.DataFrame, dict], pd.Series],
    grid: list[dict],
    train: int,
    test: int,
    embargo: int = 0,
    count_trades: Callable[[pd.Series], int] | None = None,
    periods: int = 252,
    min_trades: int = MIN_TRADES,
) -> WalkForwardResult:
    """Choose params on each train window, evaluate only on its test window.

    ``strategy(data_slice, params)`` returns per-bar strategy returns for the
    slice and must itself be causal (signal at t, return from t+1). The test
    slice is run with ``train`` bars of warm-up in front, so indicators start
    warm, and only the test bars' returns are kept.
    """
    if not grid:
        raise ValueError("empty parameter grid")
    count_trades = count_trades or _count_position_changes
    folds, oos_parts, is_parts, trial_srs = [], [], [], []
    for split in walk_forward_splits(data.index, train, test, embargo=embargo):
        train_data = data.loc[split.train]
        scored = []
        for params in grid:
            r = strategy(train_data, params)
            scored.append((sharpe(r, periods), params, r))
            trial_srs.append(sharpe(r, 1))
        best_sr, best_params, best_is = max(scored, key=lambda s: s[0])
        warm = data.loc[split.train[0]: split.test[-1]]
        oos = strategy(warm, best_params).reindex(split.test)
        folds.append(FoldResult(best_params, best_sr, sharpe(oos, periods), split.test[0], split.test[-1]))
        oos_parts.append(oos)
        is_parts.append(best_is)
    if not folds:
        raise ValueError(f"{len(data)} bars cannot fit one train={train} + embargo={embargo} + test={test} split")
    oos_returns = pd.concat(oos_parts).fillna(0.0)
    n_trades = count_trades(oos_returns)
    dsr = deflated_sharpe_ratio(oos_returns, len(grid), trial_sharpes=trial_srs)
    notes = []
    is_sr = float(np.mean([f.in_sample_sharpe for f in folds]))
    oos_sr = sharpe(oos_returns, periods)
    if is_sr > 0 and oos_sr < 0.5 * is_sr:
        notes.append("Out-of-sample Sharpe is under half of in-sample: the in-sample result is mostly fit.")
    return WalkForwardResult(folds, oos_returns, len(grid), n_trades, is_sr, oos_sr, dsr,
                             evidence_verdict(n_trades, dsr, min_trades), notes)


def _count_position_changes(returns: pd.Series) -> int:
    """Rough trade count when the strategy doesn't report one: runs of non-zero returns."""
    active = (returns != 0).astype(int)
    return int(((active.diff() == 1) | ((active == 1) & (active.shift().isna()))).sum())
