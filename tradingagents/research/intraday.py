"""Rules every intraday bar follows, before any intraday dataset exists (docs/PA_38).

A bar is public at its **end**, never its start: a 1-minute bar stamped 09:15 (bar start, as every source probed so far
labels them) covers 09:15-09:16 and is known from 09:16. A bar's end is capped at the session close, so a 60-minute bar
stamped 15:15 ends at 15:30, and a 30-minute bar a source aligns to 09:00 covers only 09:15-09:30 and ends at 09:30.
Every intraday row also carries its source; rows from two sources are never spliced into one series.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pandas as pd

SESSION_OPEN, SESSION_CLOSE = time(9, 15), time(15, 30)


def bar_known_from(bar_start: datetime, interval: timedelta) -> datetime:
    """When a bar stamped at its start becomes public: its end, capped at the session close."""
    end = bar_start + interval
    close = bar_start.replace(hour=SESSION_CLOSE.hour, minute=SESSION_CLOSE.minute, second=0, microsecond=0)
    return min(end, close)


def stamp(bars: pd.DataFrame, interval: timedelta, source: str) -> pd.DataFrame:
    """Add ``known_from`` (bar end) and ``source`` to bars indexed by their start time."""
    if not source:
        raise ValueError("every intraday row carries its source")
    out = bars.copy()
    out["known_from"] = [bar_known_from(t, interval) for t in out.index]
    out["source"] = source
    return out


def check_single_source(bars: pd.DataFrame) -> None:
    """Raise if one series mixes sources (no silent splicing)."""
    if "source" not in bars or bars["source"].isna().any():
        raise ValueError("intraday rows without a source")
    if bars["source"].nunique() > 1:
        raise ValueError(f"one series mixes sources {sorted(bars['source'].unique())}; keep them apart and labelled")
