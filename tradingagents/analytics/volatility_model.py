"""Volatility forecasts that only use the past (plan, Phase 3).

Daily returns are close to unpredictable; their size is not. This module
forecasts the annualised volatility over the next *h* sessions and scores the
forecasts against what happened.

Models:

- ``garch``  GARCH(1,1), Student-t errors
- ``gjr``    GJR-GARCH(1,1,1): falls raise volatility more than rises
- ``egarch`` EGARCH(1,1,1) (multi-step forecasts by simulation)
- ``hist``   20-session historical volatility (baseline)
- ``ewma``   RiskMetrics EWMA, lambda 0.94 (baseline)

Timing: a forecast dated *t* is made after *t*'s close from returns up to and
including *t*, and covers sessions *t+1 .. t+h*. GARCH parameters are
re-estimated every ``refit_every`` sessions on all data up to the refit date
(expanding window) and held fixed until the next refit; between refits the
variance recursion still updates with each new return. Nothing after *t* is
ever used for the forecast at *t*.

Scoring uses QLIKE on variances, ``RV/F - ln(RV/F) - 1``: robust to noise in
realised variance and harsher on under-forecasting, which is the costly error
when selling options.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Iterable

import numpy as np
import pandas as pd

ANNUAL = 252
HORIZONS = (5, 10, 21)
MIN_TRAIN = 756       # three years before the first forecast
REFIT_EVERY = 5       # weekly re-estimation

GARCH_SPECS = {
    "garch": {"vol": "GARCH", "p": 1, "q": 1},
    "gjr": {"vol": "GARCH", "p": 1, "o": 1, "q": 1},
    "egarch": {"vol": "EGARCH", "p": 1, "o": 1, "q": 1},
}


def log_returns(prices: pd.Series) -> pd.Series:
    """Daily log returns in percent (the scale ``arch`` fits best)."""
    p = prices.dropna()
    return (100.0 * np.log(p).diff()).dropna()


def _to_annual_vol(variance_sum_pct2: np.ndarray | pd.Series, horizon: int):
    """Sum of h daily variances (in %^2) -> annualised volatility as a fraction."""
    return np.sqrt(variance_sum_pct2 * ANNUAL / horizon) / 100.0


def garch_forecasts(
    returns: pd.Series,
    model: str,
    horizons: Iterable[int] = HORIZONS,
    min_train: int = MIN_TRAIN,
    refit_every: int = REFIT_EVERY,
    simulations: int = 300,
    seed: int = 0,
) -> pd.DataFrame:
    """Annualised vol forecasts per date (rows) and horizon (columns ``h5``, ``h10``...)."""
    from arch import arch_model

    spec = GARCH_SPECS[model]
    horizons = tuple(horizons)
    hmax = max(horizons)
    r = returns.dropna()
    n = len(r)
    method = "simulation" if model == "egarch" else "analytic"
    parts = []
    params = None
    for k in range(min_train - 1, n, refit_every):
        end = min(k + refit_every, n)          # forecasts for dates k .. end-1
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fitted = arch_model(r.iloc[: k + 1], mean="Constant", dist="t", **spec).fit(disp="off")
            # An estimate the optimiser did not converge on is not trusted: keep the last good one.
            if fitted.convergence_flag == 0 or params is None:
                params = fitted.params
            fixed = arch_model(r.iloc[:end], mean="Constant", dist="t", **spec).fix(params)
            kwargs = {"method": method}
            if method == "simulation":
                # arch draws the Student-t shocks itself; seed numpy's global RNG it uses.
                np.random.seed(seed + k)
                kwargs["simulations"] = simulations
            fc = fixed.forecast(start=r.index[k], horizon=hmax, reindex=False, **kwargs)
        cum = fc.variance.cumsum(axis=1).to_numpy()
        parts.append(pd.DataFrame({f"h{h}": _to_annual_vol(cum[:, h - 1], h) for h in horizons},
                                  index=fc.variance.index))
    if not parts:
        return pd.DataFrame(columns=[f"h{h}" for h in horizons])
    return pd.concat(parts).sort_index()


def hist_vol_forecasts(returns: pd.Series, horizons: Iterable[int] = HORIZONS, window: int = 20) -> pd.DataFrame:
    """Same forecast for every horizon: recent realised volatility."""
    vol = np.sqrt((returns ** 2).rolling(window).mean() * ANNUAL) / 100.0
    return pd.DataFrame({f"h{h}": vol for h in horizons}).dropna()


def ewma_forecasts(returns: pd.Series, horizons: Iterable[int] = HORIZONS, lam: float = 0.94) -> pd.DataFrame:
    var = (returns ** 2).ewm(alpha=1 - lam, adjust=False).mean()
    vol = np.sqrt(var * ANNUAL) / 100.0
    return pd.DataFrame({f"h{h}": vol for h in horizons}).iloc[30:]


def realised_vol(returns: pd.Series, horizons: Iterable[int] = HORIZONS) -> pd.DataFrame:
    """What actually happened over sessions t+1 .. t+h, dated t (NaN where the future is unknown)."""
    sq = returns ** 2
    out = {}
    for h in horizons:
        future_sum = sq[::-1].rolling(h).sum()[::-1].shift(-1)
        out[f"h{h}"] = _to_annual_vol(future_sum, h)
    return pd.DataFrame(out)


def qlike(realised_vol_: pd.Series, forecast_vol: pd.Series) -> pd.Series:
    ratio = (realised_vol_ ** 2) / (forecast_vol ** 2)
    return ratio - np.log(ratio) - 1.0


def _newey_west_t(d: pd.Series, lags: int) -> float:
    """t-statistic of the mean of ``d`` with Newey-West standard error (overlapping horizons)."""
    d = d.dropna().to_numpy(float)
    n = len(d)
    if n < 10:
        return float("nan")
    u = d - d.mean()
    s = u @ u / n
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1.0 - lag / (lags + 1.0)
        s += 2.0 * w * (u[lag:] @ u[:-lag]) / n
    return float(d.mean() / math.sqrt(s / n)) if s > 0 else float("nan")


def compare(forecasts: dict[str, pd.DataFrame], realised: pd.DataFrame, baseline: str = "hist") -> pd.DataFrame:
    """Mean QLIKE per model and horizon on the dates every model covers, and a
    Diebold-Mariano style t-stat of each model's loss minus the baseline's
    (negative = better than the baseline)."""
    rows = []
    for col in realised.columns:
        h = int(col[1:])
        frame = pd.concat({m: f[col] for m, f in forecasts.items()} | {"_rv": realised[col]}, axis=1).dropna()
        if frame.empty:
            continue
        losses = {m: qlike(frame["_rv"], frame[m]) for m in forecasts}
        for m, loss in losses.items():
            diff = loss - losses[baseline] if baseline in losses else pd.Series(dtype=float)
            rows.append({"horizon": h, "model": m, "qlike": float(loss.mean()), "n": len(loss),
                         "vs_baseline_t": _newey_west_t(diff, h) if m != baseline else 0.0})
    return pd.DataFrame(rows)
