"""Swing points and chart patterns that never look into the future.

A swing high at bar *i* is "the highest high from i-left to i+right" — which
cannot be known until bar *i+right* has printed. Charting code usually stamps
the swing on bar *i*, so a double top or a "break of structure" appears on the
chart (and in a backtest) ``right`` bars before anyone could have seen it. The
backtest then trades on information from the future and looks far better than
live trading will.

Here every swing carries two dates: ``pivot_at`` (where it is on the chart) and
``confirmed_at`` (the first bar on which it is knowable). Anything that drives
a decision on bar *t* uses only swings with ``confirmed_at <= t``.

``find_lookahead`` proves it for any signal function: it recomputes the signal
on data truncated at each bar and compares it with the full-history result. A
signal that changes its past values when future bars arrive repaints, and the
function returns the bars where it does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Swing:
    kind: str                  # "high" | "low"
    pivot_at: pd.Timestamp
    confirmed_at: pd.Timestamp
    price: float


def confirmed_swings(df: pd.DataFrame, left: int = 3, right: int = 3) -> list[Swing]:
    """Fractal swings of ``High``/``Low``, each stamped with the bar that confirms it.

    A pivot needs ``right`` later bars, so the last ``right`` bars of the frame
    can never hold a confirmed swing — exactly as in live trading.
    """
    highs, lows, idx = df["High"].to_numpy(), df["Low"].to_numpy(), df.index
    swings = []
    for i in range(left, len(df) - right):
        window_h = highs[i - left: i + right + 1]
        window_l = lows[i - left: i + right + 1]
        # Strictly greater than the left side, at least as great as the right:
        # a flat top yields one swing, not several.
        if highs[i] == window_h.max() and (highs[i - left: i] < highs[i]).all():
            swings.append(Swing("high", idx[i], idx[i + right], float(highs[i])))
        if lows[i] == window_l.min() and (lows[i - left: i] > lows[i]).all():
            swings.append(Swing("low", idx[i], idx[i + right], float(lows[i])))
    return swings


def swings_known_at(swings: list[Swing], t: pd.Timestamp) -> list[Swing]:
    return [s for s in swings if s.confirmed_at <= t]


def market_structure(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.Series:
    """Per bar: the structure label from the last two *confirmed* highs and lows.

    "HH/HL" uptrend, "LH/LL" downtrend, otherwise "mixed"; "" until enough swings exist.
    """
    swings = confirmed_swings(df, left, right)
    labels = pd.Series("", index=df.index, dtype=object)
    for t in df.index:
        known = swings_known_at(swings, t)
        hs = [s.price for s in known if s.kind == "high"][-2:]
        ls = [s.price for s in known if s.kind == "low"][-2:]
        if len(hs) < 2 or len(ls) < 2:
            continue
        up, down = hs[1] > hs[0] and ls[1] > ls[0], hs[1] < hs[0] and ls[1] < ls[0]
        labels[t] = "HH/HL" if up else "LH/LL" if down else "mixed"
    return labels


def double_top_breakdown(
    df: pd.DataFrame,
    tolerance: float = 0.015,
    min_separation: int = 10,
    left: int = 3,
    right: int = 3,
) -> pd.Series:
    """True on the bar whose close breaks below the neckline of a confirmed double top.

    Two confirmed swing highs within ``tolerance`` of each other and at least
    ``min_separation`` bars apart; the neckline is the lowest low between them.
    Only swings confirmed by bar *t* are used, so the signal fires when a trader
    could have acted, never earlier.
    """
    swings = confirmed_swings(df, left, right)
    position = {ts: i for i, ts in enumerate(df.index)}
    signal = pd.Series(False, index=df.index)
    closes, lows = df["Close"], df["Low"]
    for t in df.index:
        highs = [s for s in swings_known_at(swings, t) if s.kind == "high"][-2:]
        if len(highs) < 2:
            continue
        first, second = highs
        if position[second.pivot_at] - position[first.pivot_at] < min_separation:
            continue
        if abs(second.price - first.price) / first.price > tolerance:
            continue
        neckline = lows.loc[first.pivot_at:second.pivot_at].min()
        previous = df.index[position[t] - 1] if position[t] else None
        crossed = closes[t] < neckline and (previous is None or closes[previous] >= neckline)
        signal[t] = bool(crossed)
    return signal


def find_lookahead(
    signal_fn: Callable[[pd.DataFrame], pd.Series],
    df: pd.DataFrame,
    start: int = 30,
    step: int = 1,
) -> list[pd.Timestamp]:
    """Bars where ``signal_fn`` on the full history disagrees with what it said live.

    For each bar *t* (from ``start``), the signal is computed on ``df`` up to *t*
    and its last value compared with the full-history value at *t*. An empty
    list means the signal is causal; anything else is look-ahead (repainting).
    """
    full = signal_fn(df)
    mismatches = []
    for i in range(start, len(df), step):
        live = signal_fn(df.iloc[: i + 1])
        t = df.index[i]
        a, b = live.iloc[-1], full.loc[t]
        if not (a == b or (pd.isna(a) and pd.isna(b))):
            mismatches.append(t)
    return mismatches
