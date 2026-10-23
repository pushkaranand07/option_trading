"""Model features per (session, stock), each using only data before the session (plan, Phase 6).

Everything is computed on the wide price panel (``evaluate.panel``) and then
shifted one row, so the row for session *t* describes the market up to the
close of *t-1*: what a trader knows before *t* opens.

Groups:

- price:     returns over 1/5/20/60 sessions, distance from 20/50/200-session
             averages, RSI-14, ATR %, Bollinger position, volatility and its
             ratio to the longer-run level, distance from the 252-session high
- volume:    volume vs its 20-session average (z-score of log volume)
- structure: confirmed swing structure (+1 higher highs/lows, -1 lower, 0 mixed)
- context:   any series passed in ``context`` (e.g. NIFTY 20-day return, India
             VIX, regime probabilities), dated by the close they are known after
- extra:     wide per-stock frames, or functions ``data -> frame``, passed in
             ``extra`` (e.g. OI change, delivery %), dated the same way. Give a
             function where you can: :func:`leak_check` recomputes functions on
             cut-off data and so can catch them peeking; a ready-made frame it
             can only pass through.

No raw calendar features (weekday, month): eight years hold eight Januaries,
far too few to learn a month effect, and the first real run ranked ``month``
as its top feature: the model fitting noise. Event-based calendar features
(days to expiry, results season) come from the NSE store.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from tradingagents.analytics.swings import market_structure

STRUCTURE_CODE = {"HH/HL": 1.0, "LH/LL": -1.0, "mixed": 0.0, "": np.nan}


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, min_periods=n).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, min_periods=n).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, np.nan))


def _atr_pct(data: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    high, low, close = data["high"], data["low"], data["close"]
    prev = close.shift(1)
    tr = np.maximum(np.maximum(high - low, (high - prev).abs()), (low - prev).abs())
    return tr.ewm(alpha=1 / n, min_periods=n).mean() / close


def _structure(data: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for s in data["close"].columns:
        df = pd.DataFrame({"High": data["high"][s], "Low": data["low"][s]}).dropna()
        out[s] = market_structure(df).map(STRUCTURE_CODE).reindex(data.index)
    return pd.DataFrame(out)


def price_features(data: pd.DataFrame, with_structure: bool = True) -> dict[str, pd.DataFrame]:
    """Wide frames per feature, dated by the close they use (not yet shifted)."""
    close = data["close"]
    logc = np.log(close)
    r1 = logc.diff()
    vol20 = r1.rolling(20).std()
    f = {
        "ret_1": r1, "ret_5": logc.diff(5), "ret_20": logc.diff(20), "ret_60": logc.diff(60),
        "dist_ma20": close / close.rolling(20).mean() - 1,
        "dist_ma50": close / close.rolling(50).mean() - 1,
        "dist_ma200": close / close.rolling(200).mean() - 1,
        "rsi14": _rsi(close),
        "atr_pct": _atr_pct(data),
        "bb_pos": (close - close.rolling(20).mean()) / (2 * close.rolling(20).std()),
        "vol20": vol20,
        "vol_ratio": vol20 / r1.rolling(120).std(),
        "dist_high252": close / close.rolling(252, min_periods=126).max() - 1,
    }
    logv = np.log(data["volume"].replace(0, np.nan))
    f["volume_z20"] = (logv - logv.rolling(20).mean()) / logv.rolling(20).std()
    if with_structure:
        f["structure"] = _structure(data)
    return f


def build(
    data: pd.DataFrame,
    context: Mapping[str, pd.Series] | None = None,
    extra: Mapping[str, pd.DataFrame | Callable[[pd.DataFrame], pd.DataFrame]] | None = None,
    with_structure: bool = True,
) -> pd.DataFrame:
    """Long frame indexed by (date, symbol): every feature as known before that session opened."""
    wide = price_features(data, with_structure)
    for name, frame in (extra or {}).items():
        frame = frame(data) if callable(frame) else frame
        wide[name] = frame.reindex(index=data.index, columns=data["close"].columns)
    symbols = data["close"].columns
    for name, series in (context or {}).items():
        s = series.reindex(data.index)
        wide[name] = pd.DataFrame({sym: s for sym in symbols}, index=data.index)
    # One-row shift: session t sees the close of t-1 and earlier only.
    stacked = {name: frame.shift(1).stack(future_stack=True) for name, frame in wide.items()}
    long = pd.DataFrame(stacked)
    long.index.names = ["date", "symbol"]
    return long.sort_index()


def leak_check(data: pd.DataFrame, samples: int = 8, seed: int = 0, **build_kwargs) -> int:
    """Sessions whose features change when that session's own prices (or later ones) change.

    For sampled sessions *i*: build on data cut after *i* with row *i* scrambled, and
    compare with the full build. ``extra`` functions are recomputed on the cut data and
    so are checked; ready-made context/extra frames pass through unchanged and must
    already be dated by the close they are known after.
    """
    rng = np.random.default_rng(seed)
    full = build(data, **build_kwargs)
    n = len(data)
    picks = sorted(set(rng.integers(max(260, n // 3), n, size=samples).tolist()))
    bad = 0
    for i in picks:
        cut = data.iloc[: i + 1].copy()
        cut.iloc[-1] = cut.iloc[-1] * rng.uniform(0.5, 1.5, cut.shape[1])
        part = build(cut, **build_kwargs)
        day = data.index[i]
        a = full.loc[day].sort_index().to_numpy(float)
        b = part.loc[day].sort_index().to_numpy(float)
        if a.shape != b.shape or not np.allclose(a, b, equal_nan=True):
            bad += 1
    return bad
