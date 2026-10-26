"""Web app speed without stale answers: one fetch per key, refresh-ahead, stale-bar detection, latency report."""

import threading
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from webapp import latency, market_data as md, planner, signals as sg


@pytest.mark.unit
def test_callers_that_miss_together_share_one_fetch():
    cache, calls = md._TTLCache(), []

    def slow():
        calls.append(1)
        time.sleep(0.2)
        return "bars"

    out = []
    threads = [threading.Thread(target=lambda: out.append(cache.get("k", 5, slow))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(calls) == 1 and out == ["bars"] * 8


@pytest.mark.unit
def test_an_older_fetch_never_replaces_a_newer_one():
    cache = md._TTLCache()

    def old():
        time.sleep(0.3)
        return "old"

    t = threading.Thread(target=lambda: cache._fetch("k", old))
    t.start()
    time.sleep(0.05)
    assert cache._fetch("k", lambda: "new") == "new"   # started later, finished first
    t.join()
    assert cache.get("k", 60, lambda: "refetched") == "new"


@pytest.mark.unit
def test_a_value_is_never_served_older_than_its_ttl():
    cache, n = md._TTLCache(), iter(range(100))
    first = cache.get("k", 0.1, lambda: next(n))
    time.sleep(0.15)
    assert cache.get("k", 0.1, lambda: next(n)) == first + 1


@pytest.mark.unit
def test_refresh_ahead_refetches_hot_keys_before_expiry_and_leaves_cold_ones(monkeypatch):
    cache, n = md._TTLCache(), iter(range(100))
    cache.get("hot", 1.0, lambda: next(n))
    cache.get("cold", 1.0, lambda: next(n))
    with cache._lock:                                   # "cold" was last read long ago
        fn, ttl, _ = cache._uses["cold"]
        cache._uses["cold"] = (fn, ttl, time.monotonic() - cache.HOT_SECONDS - 1)
    assert cache.refresh_ahead() == 0                   # neither is near expiry yet
    time.sleep(0.65)                                    # within the lead (40% of a 1 s ttl)
    assert cache.refresh_ahead() == 1
    assert cache.get("hot", 1.0, lambda: "miss") == 2   # served from memory, refreshed in the background


@pytest.mark.unit
def test_a_failing_refresh_backs_off_and_keeps_the_last_value():
    cache = md._TTLCache()
    cache.get("k", 0.2, lambda: "good")

    def down():
        raise ConnectionError("Yahoo down")

    with cache._lock:
        cache._uses["k"] = (down, 0.2, time.monotonic())
    time.sleep(0.15)
    assert cache.refresh_ahead() == 0 and "k" in cache._failed
    assert cache.refresh_ahead() == 0                   # backing off: not retried every tick
    assert cache._d["k"][1] == "good"


@pytest.mark.unit
def test_fetches_are_timed_by_kind():
    latency.reset()
    cache = md._TTLCache()
    cache.get(("c", "NIFTY", "5m"), 5, lambda: 1)
    rep = latency.report()
    assert rep["fetch c"]["count"] == 1 and set(rep["fetch c"]) == {"count", "p50_ms", "p95_ms", "p99_ms", "max_ms"}


@pytest.mark.unit
def test_percentiles():
    latency.reset()
    for ms in range(1, 101):
        latency.observe("x", ms / 1000)
    r = latency.report()["x"]
    assert (r["p50_ms"], r["p95_ms"], r["p99_ms"], r["max_ms"]) == (51.0, 95.0, 99.0, 100.0)


def _bars(last: datetime, n: int = 20) -> pd.DataFrame:
    idx = pd.date_range(end=last, periods=n, freq="5min")
    return pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0}, index=idx)


@pytest.mark.unit
def test_stale_bars_only_while_the_market_is_open():
    now = datetime(2026, 10, 26, 11, 0, tzinfo=md.IST)
    fresh, old = _bars(now - timedelta(minutes=4)), _bars(now - timedelta(minutes=11))
    assert md.stale_bars(fresh, "5m", True, now) is None
    assert md.stale_bars(old, "5m", True, now) == pytest.approx(660)
    assert md.stale_bars(old, "5m", False, now) is None          # after the close the last bar is old by nature
    assert md.stale_bars(old, "1D", True, now) is None


def _walk(index, seed):
    rng = np.random.default_rng(seed)
    close = 22000 + np.cumsum(rng.normal(0, 8, len(index)))
    return pd.DataFrame({"open": close, "high": close + 5, "low": close - 5, "close": close, "volume": 1000.0},
                        index=index)


@pytest.fixture
def plan_feed(monkeypatch):
    now = datetime(2026, 10, 26, 11, 0, tzinfo=md.IST)
    days = pd.bdate_range(end=now.date(), periods=30)
    idx5 = pd.DatetimeIndex([d + pd.Timedelta(minutes=555 + 5 * i) for d in days for i in range(75)]).tz_localize(md.IST)
    feed = {"5m": _walk(idx5[idx5 < now], 1), "1D": _walk(pd.bdate_range(end=now.date(), periods=300, tz=md.IST), 2),
            "source": "yahoo"}
    monkeypatch.setattr(md, "candles", lambda s, tf="5m": (feed[tf], feed["source"]))
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": "NIFTY", "name": "NIFTY 50", "kind": "INDEX",
                                                     "lot": 65, "step": 50})
    monkeypatch.setattr(sg, "market_open", lambda *a, **k: True)
    monkeypatch.setattr(sg, "now_ist", lambda: now)
    return feed


@pytest.mark.unit
def test_a_plan_on_current_bars_is_not_blocked_for_staleness(plan_feed):
    p = planner.build_plan("NIFTY")
    assert p["data"]["stale"] is False and p["data"]["last_bar_age_s"] == 300
    assert not any("old" in b or "No live prices" in b for b in p["verdict"]["blockers"])


@pytest.mark.unit
def test_a_plan_on_a_stopped_feed_is_blocked(plan_feed):
    plan_feed["5m"] = plan_feed["5m"].iloc[:-4]                   # the last bar started 25 min ago
    p = planner.build_plan("NIFTY")
    assert p["data"]["stale"] is True and p["verdict"]["safe"] is False
    assert any("25 min old" in b for b in p["verdict"]["blockers"])


@pytest.mark.unit
def test_a_plan_on_saved_bars_is_blocked_while_the_market_is_open(plan_feed):
    plan_feed["source"] = "saved (last bar 26-Oct 10:55)"
    p = planner.build_plan("NIFTY")
    assert p["verdict"]["safe"] is False and any("No live prices" in b for b in p["verdict"]["blockers"])
