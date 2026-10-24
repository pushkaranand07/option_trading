"""Volatility forecasts from a pretrained time-series model (plan, Phase 7).

Amazon Chronos-Bolt is fed the daily log returns up to and including *t* (the last
``context`` sessions) and returns quantile forecasts for each of the next sessions.
Each session's spread of outcomes becomes a variance, and the variances over
*t+1 .. t+h* are summed exactly as ``volatility_model`` does for GARCH, so the
forecasts are scored on the same dates with the same QLIKE loss.

Pre-declared before any result was seen (two trials):

- ``chronos``      raw: per-session sigma = (q90 - q10) / 2.563 (the normal
                   inter-decile width), variance = sigma^2 + median^2 (realised
                   variance is not demeaned either)
- ``chronos_cal``  the raw forecast times one scale factor per symbol and horizon,
                   learnt only from earlier forecasts whose realised window had
                   closed by *t* (ratio of mean realised to mean forecast variance,
                   expanding, at least ``min_obs`` pairs). Returns are fat-tailed, so
                   the inter-decile width understates variance; this corrects the
                   level without letting the future in.

Keep rule: ``chronos_cal`` (or ``chronos``) has a lower pooled QLIKE than GARCH at
10 sessions and beats GARCH on at least two thirds of symbols; otherwise rejected.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd

from tradingagents.analytics.volatility_model import HORIZONS, MIN_TRAIN, _to_annual_vol

MODEL_ID = "amazon/chronos-bolt-small"
CONTEXT = 512
INTERDECILE = 2.5631          # q90 - q10 of a standard normal


def load_pipeline(model_id: str = MODEL_ID):
    import torch
    from chronos import BaseChronosPipeline

    return BaseChronosPipeline.from_pretrained(model_id, device_map="cpu", torch_dtype=torch.float32)


def chronos_forecasts(
    returns: pd.Series,
    pipe,
    horizons: Iterable[int] = HORIZONS,
    min_train: int = MIN_TRAIN,
    context: int = CONTEXT,
    batch: int = 256,
) -> pd.DataFrame:
    """Annualised vol forecasts per date (rows) and horizon (``h5``, ``h10``...), raw.

    ``returns`` are daily log returns in percent. The forecast dated *t* sees
    returns up to and including *t* only; the first is at position ``min_train - 1``,
    the same first date as ``garch_forecasts``.
    """
    import torch

    horizons = tuple(horizons)
    hmax = max(horizons)
    r = returns.dropna()
    values = r.to_numpy(np.float32)
    positions = range(min_train - 1, len(r))
    rows = []
    for start in range(0, len(positions), batch):
        chunk = positions[start:start + batch]
        ctx = [torch.tensor(values[max(0, k + 1 - context): k + 1]) for k in chunk]
        q, _ = pipe.predict_quantiles(ctx, prediction_length=hmax, quantile_levels=[0.1, 0.5, 0.9])
        q = q.numpy().astype(float)                         # (series, step, quantile)
        sigma = (q[:, :, 2] - q[:, :, 0]) / INTERDECILE
        var = sigma ** 2 + q[:, :, 1] ** 2
        cum = var.cumsum(axis=1)
        rows.append(pd.DataFrame({f"h{h}": _to_annual_vol(cum[:, h - 1], h) for h in horizons},
                                 index=r.index[list(chunk)]))
    if not rows:
        return pd.DataFrame(columns=[f"h{h}" for h in horizons])
    return pd.concat(rows)


def calibrate(forecasts: pd.DataFrame, realised: pd.DataFrame, min_obs: int = 252) -> pd.DataFrame:
    """Scale each horizon's forecasts by mean(RV^2) / mean(F^2) over earlier forecast
    dates whose realised window had closed by the forecast date (causal, expanding)."""
    out = {}
    for col in forecasts.columns:
        h = int(col[1:])
        f = forecasts[col]
        rv = realised[col].reindex(f.index)
        both = f.notna() & rv.notna()
        f2 = (f ** 2).where(both, 0.0).cumsum()
        rv2 = (rv ** 2).where(both, 0.0).cumsum()
        count = both.astype(int).cumsum()
        # The window of the forecast dated s closes at s+h sessions: at t only s <= t-h are known.
        known_f2, known_rv2, known_n = f2.shift(h), rv2.shift(h), count.shift(h)
        scale = (known_rv2 / known_f2).where(known_n >= min_obs)
        out[col] = f * np.sqrt(scale)
    return pd.DataFrame(out).dropna(how="all")
