"""Measured latency: the last few thousand durations per name, reported as p50 / p95 / p99.

Names are ``api <route>`` for a whole request and ``fetch <kind>`` for one data fetch or calculation
behind the cache (Yahoo / NSE / Dhan candles, quotes, chains, the plan, risk), so a slow page can be traced
to the stage that made it slow.
"""

from __future__ import annotations

import threading
from collections import deque

KEEP = 2000

_samples: dict[str, deque] = {}
_lock = threading.Lock()


def observe(name: str, seconds: float) -> None:
    with _lock:
        _samples.setdefault(name, deque(maxlen=KEEP)).append(seconds)


def _pct(xs: list[float], p: float) -> float:
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def report() -> dict[str, dict]:
    """{name: {count, p50_ms, p95_ms, p99_ms, max_ms}} over the kept samples, slowest p95 first."""
    with _lock:
        snap = {k: sorted(v) for k, v in _samples.items() if v}
    out = {k: {"count": len(xs), "p50_ms": round(_pct(xs, 50) * 1000, 1), "p95_ms": round(_pct(xs, 95) * 1000, 1),
               "p99_ms": round(_pct(xs, 99) * 1000, 1), "max_ms": round(xs[-1] * 1000, 1)} for k, xs in snap.items()}
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["p95_ms"]))


def reset() -> None:
    with _lock:
        _samples.clear()
