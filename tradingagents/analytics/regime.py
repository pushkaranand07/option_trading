"""Market regime from a 3-state Gaussian HMM, using only the past (plan, Phase 4).

Features, each known after day *d*'s close (NIFTY unless stated):

- ``r5``, ``r20``   5- and 20-session log returns
- ``rv20``          20-session realised volatility, annualised
- ``vix``           India VIX level (log)
- ``vix_chg5``      5-session change in log India VIX
- ``breadth``       share of the universe's stocks above their 50-session average

Model: ``hmmlearn.GaussianHMM`` with 3 states, fitted on an expanding window and
refitted every ``refit_every`` sessions. Features are standardised with the
training window's mean and deviation only.

Look-ahead: ``hmmlearn``'s ``predict_proba`` is *smoothed* (forward-backward),
so each day's probability uses later days too. This module runs the forward
filter itself: the probability on day *d* uses observations up to *d* only.

Naming: an HMM's state numbers are arbitrary and change between refits. States
are ordered by the volatility of their mean (``rv20``) and named ``calm``,
``choppy``, ``stress``, so a name means the same thing after every refit.

A label changes only when the new state's probability exceeds ``switch_prob``
for ``switch_days`` sessions in a row, so it does not flicker.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

import numpy as np
import pandas as pd
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

NAMES = ("calm", "choppy", "stress")
FEATURES = ("r5", "r20", "rv20", "vix", "vix_chg5", "breadth")
MIN_TRAIN = 756
REFIT_EVERY = 63          # quarterly


def features(index_close: pd.Series, vix: pd.Series, stock_closes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Feature table dated by the close each row is known after."""
    c = index_close.dropna()
    logc = np.log(c)
    r1 = logc.diff()
    out = pd.DataFrame({
        "r5": logc.diff(5),
        "r20": logc.diff(20),
        "rv20": r1.rolling(20).std() * np.sqrt(252),
    })
    lv = np.log(vix.reindex(out.index))
    out["vix"] = lv
    out["vix_chg5"] = lv.diff(5)
    if stock_closes is not None and not stock_closes.empty:
        sc = stock_closes.reindex(out.index)
        ma = sc.rolling(50, min_periods=50).mean()
        out["breadth"] = (sc > ma).sum(axis=1) / ma.notna().sum(axis=1).replace(0, np.nan)
    return out.dropna()


def _fit(X: np.ndarray, seed: int, starts: int = 5):
    """Best of several EM starts. ``min_covar`` keeps a state whose feature barely
    moves (a flat VIX stretch) from collapsing to a singular covariance."""
    import logging

    from hmmlearn.hmm import GaussianHMM

    logging.getLogger("hmmlearn").setLevel(logging.ERROR)   # per-start convergence chatter
    best = None
    for s in range(starts):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = GaussianHMM(n_components=3, covariance_type="full", n_iter=300, tol=1e-4,
                            min_covar=1e-2, random_state=seed + s)
            try:
                m.fit(X)
                score = m.score(X)
            except (ValueError, np.linalg.LinAlgError):
                continue
        if np.isfinite(score) and (best is None or score > best[0]):
            best = (score, m)
    if best is None:
        raise RuntimeError("HMM failed to fit from every start")
    return best[1]


def _log_emissions(model, X: np.ndarray) -> np.ndarray:
    return np.column_stack([
        multivariate_normal(model.means_[k], model.covars_[k], allow_singular=True).logpdf(X)
        for k in range(model.n_components)
    ]).reshape(len(X), model.n_components)


def forward_filter(model, X: np.ndarray, log_prior: np.ndarray | None = None) -> np.ndarray:
    """P(state_t | x_1..x_t) for each t: the forward algorithm, normalised every step."""
    log_e = _log_emissions(model, X)
    log_a = np.log(model.transmat_ + 1e-300)
    log_alpha = np.empty_like(log_e)
    prev = np.log(model.startprob_ + 1e-300) if log_prior is None else log_prior
    for t in range(len(X)):
        pred = prev if (t == 0 and log_prior is None) else logsumexp(prev[:, None] + log_a, axis=0)
        cur = pred + log_e[t]
        cur -= logsumexp(cur)
        log_alpha[t] = cur
        prev = cur
    return np.exp(log_alpha)


def regime_probabilities(
    feats: pd.DataFrame,
    min_train: int = MIN_TRAIN,
    refit_every: int = REFIT_EVERY,
    seed: int = 0,
) -> pd.DataFrame:
    """Filtered probabilities ``p_calm``, ``p_choppy``, ``p_stress`` per date, from ``min_train`` on.

    At each refit the model is fitted on all rows up to the refit date. The
    filter then runs over the whole history up to each date with that model's
    parameters, which needs nothing after the date.
    """
    X_all = feats.to_numpy(float)
    vol_col = list(feats.columns).index("rv20")
    parts = []
    for k in range(min_train - 1, len(feats), refit_every):
        end = min(k + refit_every, len(feats))
        mu, sd = X_all[: k + 1].mean(axis=0), X_all[: k + 1].std(axis=0)
        sd[sd == 0] = 1.0
        Z = (X_all - mu) / sd
        model = _fit(Z[: k + 1], seed)
        order = np.argsort(model.means_[:, vol_col])      # calm, choppy, stress by volatility
        probs = forward_filter(model, Z[:end])[k:end][:, order]
        parts.append(pd.DataFrame(probs, index=feats.index[k:end], columns=[f"p_{n}" for n in NAMES]))
    if not parts:
        return pd.DataFrame(columns=[f"p_{n}" for n in NAMES])
    return pd.concat(parts)


def stable_labels(probs: pd.DataFrame, switch_prob: float = 0.7, switch_days: int = 2) -> pd.Series:
    """The regime name, changed only after ``switch_days`` sessions above ``switch_prob``."""
    names = [c.removeprefix("p_") for c in probs.columns]
    values = probs.to_numpy()
    labels, current, streak_name, streak = [], None, None, 0
    for row in values:
        top = int(row.argmax())
        name = names[top]
        if current is None:
            current = name
        if name != current and row[top] > switch_prob:
            streak = streak + 1 if name == streak_name else 1
            streak_name = name
            if streak >= switch_days:
                current, streak, streak_name = name, 0, None
        else:
            streak, streak_name = 0, None
        labels.append(current)
    return pd.Series(labels, index=probs.index, name="regime")


def describe(labels: pd.Series, index_close: pd.Series, horizons: Iterable[int] = (5, 21)) -> pd.DataFrame:
    """Per regime: share of days, and the *following* returns and volatility (what a label is worth)."""
    logc = np.log(index_close.reindex(labels.index).ffill())
    r1 = logc.diff()
    rows = []
    for name in NAMES:
        mask = labels == name
        row = {"regime": name, "days": int(mask.sum()), "share": float(mask.mean())}
        for h in horizons:
            fwd = (logc.shift(-h) - logc)[mask]
            fwd_vol = (r1[::-1].rolling(h).std()[::-1].shift(-1) * np.sqrt(252))[mask]
            row[f"next{h}_ret"] = float(fwd.mean())
            row[f"next{h}_vol"] = float(fwd_vol.mean())
        rows.append(row)
    return pd.DataFrame(rows).set_index("regime")
