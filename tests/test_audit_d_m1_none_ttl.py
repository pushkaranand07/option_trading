"""Audit M1 follow-up (verifier defect 4): a failed reference lookup (no bars, no Dhan) is cached only briefly
(PREV_MISS_TTL, 30 s), not for the full 600 s; a found close still keeps 600 s. Fakes only; the cache entry is aged
by hand instead of patching the clock."""

from datetime import date

import pytest

from tests.test_audit_d_m1_prev_close import CAL, bars
from webapp import market_data as md

MISS_TTL = getattr(md, "PREV_MISS_TTL", 30)
KEY = ("prev", "NIFTY", "2026-11-08")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "index_lots", lambda: {})
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    state = {"fail": True, "calls": 0}

    def fake_candles(inst, tf):
        state["calls"] += 1
        if state["fail"]:
            raise md.DataError("Yahoo unreachable and nothing saved")
        return bars(), "yahoo"

    monkeypatch.setattr(md, "_candles", fake_candles)
    return state


def age(seconds):
    started, value = md._cache._d[KEY]
    md._cache._d[KEY] = (started - seconds, value)


def ask():
    return md.prev_close(md.instrument("NIFTY"), date(2026, 11, 8), vendor=24536.6, vendor_source="yahoo",
                         calendar=CAL)


@pytest.mark.unit
def test_a_failed_lookup_is_retried_after_the_short_ttl(env):
    assert ask()[1] == "yahoo" and env["calls"] == 1
    age(5)
    assert ask()[1] == "yahoo" and env["calls"] == 1           # within the short TTL: not hammered
    env["fail"] = False                                          # Yahoo is back
    age(MISS_TTL)
    assert ask()[:2] == (25030.35, "bars (yahoo)") and env["calls"] == 2


@pytest.mark.unit
def test_a_found_close_keeps_the_long_ttl(env):
    env["fail"] = False
    assert ask()[0] == 25030.35 and env["calls"] == 1
    age(MISS_TTL + 1)
    assert ask()[0] == 25030.35 and env["calls"] == 1
    age(600)
    ask()
    assert env["calls"] == 2
