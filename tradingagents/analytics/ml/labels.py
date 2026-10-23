"""Triple-barrier labels on closes (plan, Phase 6).

For a long entry at the **open** of session *t* (price ``E``), the barriers are
``E * (1 +/- k * sigma_t * sqrt(H))``, where ``sigma_t`` is a daily volatility
known before *t* opens. Walking forward from *t*'s own close, the trade exits
after the first close beyond either barrier, or at the time limit of ``H``
sessions (``exit_reason``: upper / lower / time).

``label`` is 1 when that exit's return is positive. Not "upper barrier first":
that label depends on the barrier width, so volatility features predict it
even on pure noise (narrow barriers get hit more), an AUC with no trading
edge behind it. Whether the trade made money does not depend on the width
when there is no real edge.

Closes, not intraday highs/lows, because the user trades by hand after the
close: a barrier crossed at the close of session *s* is acted on at the open
of *s+1*. So the trade exits at ``open(s+1)`` (or ``open(t+H)`` at the time
limit), and ``ret`` is that realised open-to-open return.

``t1`` is the last session whose price the label depends on (the exit open).
Validation purges any training sample whose ``t1`` reaches the test window.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def causal_daily_vol(close: pd.DataFrame, span: int = 20) -> pd.DataFrame:
    """EWMA daily vol of close-to-close log returns, dated so row *t* uses closes up to *t-1*."""
    r = np.log(close).diff()
    return np.sqrt((r ** 2).ewm(span=span, min_periods=span).mean()).shift(1)


def triple_barrier(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    sigma: pd.DataFrame,
    k: float = 1.0,
    horizon: int = 10,
) -> pd.DataFrame:
    """One row per (session, symbol) with a label: ``label``, ``ret``, ``exit_reason``, ``t1``, ``sessions``.

    Rows whose barrier window runs past the data are omitted (their outcome is unknown).
    """
    idx = opens.index
    n = len(idx)
    rows = []
    for symbol in opens.columns:
        o = opens[symbol].to_numpy(float)
        c = closes[symbol].reindex(idx).to_numpy(float)
        s = sigma[symbol].reindex(idx).to_numpy(float)
        for t in range(n):
            if t + horizon >= n or not (np.isfinite(o[t]) and np.isfinite(s[t]) and s[t] > 0):
                continue
            width = k * s[t] * np.sqrt(horizon)
            up, dn = o[t] * (1 + width), o[t] * (1 - width)
            exit_i, reason = t + horizon, "time"
            for j in range(t, t + horizon):
                if not np.isfinite(c[j]):
                    continue
                if c[j] >= up:
                    exit_i, reason = j + 1, "upper"
                    break
                if c[j] <= dn:
                    exit_i, reason = j + 1, "lower"
                    break
            if not np.isfinite(o[exit_i]):
                continue
            ret = o[exit_i] / o[t] - 1.0
            rows.append((idx[t], symbol, int(ret > 0), ret, reason, idx[exit_i], exit_i - t))
    return pd.DataFrame(rows, columns=["date", "symbol", "label", "ret", "exit_reason", "t1", "sessions"])
