"""Audit step 3b: quotes may be up to 120 s old at a Take (it was 60 s, which refused most Takes), and each trade or
refusal keeps the quotes' age; the settlement script may run its interim count (counts only, no prices) on the real
v2 registry, while the stop stays locked; repeated refusals of the same trade are one row with an attempt count."""

import importlib.util

import pytest

from tests.test_step3_v2_status import LEGS, register
from tests.test_take_honest_entry import chain, take, world  # noqa: F401  (world is a fixture)
from tradingagents.research import ai_settle
from webapp import ai_test, trade_record as tr


def stamped(ts, **kw):
    return chain(**kw) | {"timestamp": ts}


@pytest.mark.unit
def test_quotes_100_s_old_are_taken_and_their_age_is_stored(world):
    world["live"]["chain"] = stamped("05-Nov-2026 09:58:20")                      # the clock reads 10:00:00
    r = take(world)
    assert r.status_code == 200, r.text
    assert r.json()["quote_age_s"] == 100


@pytest.mark.unit
def test_quotes_121_s_old_are_refused_and_the_refused_row_keeps_the_age(world):
    world["live"]["chain"] = stamped("05-Nov-2026 09:57:59")
    r = take(world)
    assert r.status_code == 400 and "121 s old (limit 120 s)" in r.json()["detail"]
    [row] = tr.overview(lambda *a: chain())["you"]["not_taken"]
    assert row["quote_age_s"] == 121


@pytest.mark.unit
def test_repeated_refusals_of_one_trade_are_one_row_with_the_attempts(world):
    world["live"]["chain"] = chain(spot=world["call"]["plan"]["underlying_entry_high"] + 30)
    take(world)
    world["live"]["chain"] = stamped("05-Nov-2026 09:57:00")
    take(world)
    [row] = tr.overview(lambda *a: chain())["you"]["not_taken"]
    assert row["attempts"] == 2 and "s old" in row["reason"]                        # the last reason is kept
    tr.record_ai_pick("run1")
    tr.record_ai_pick("run1")
    o = tr.overview(lambda *a: chain())
    assert len(o["ai"]["not_taken"]) == 1 and o["ai"]["not_taken"][0]["attempts"] == 2


@pytest.fixture
def script(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ai_test_settle", ai_test.ROOT / "scripts" / "ai_test_settle.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    path = tmp_path / "real.jsonl"
    monkeypatch.setattr(ai_test, "REGISTRY", path)
    monkeypatch.setattr(mod, "REAL_REGISTRY", path)                             # this file plays the real registry
    return mod, path


@pytest.mark.unit
def test_the_interim_count_runs_on_the_real_registry_and_the_stop_stays_locked(script):
    from datetime import date

    mod, path = script
    register((2026, 11, 5))                                                     # a real (non-synthetic) NIFTY row
    out = mod.run(path, path.parent, {}, {date(2026, 11, 5)}, ai_test.SPEC_SHA256, mode="interim")
    assert (out["questions"], out["trades"], out["entered"], out["void"]) == (1, 1, 1, 0)
    assert not any(k in out for k in ("net", "pnl", "mean", "report")) and LEGS
    with pytest.raises(ai_settle.RealRowsRefused):
        mod.run(path, path.parent, {}, {date(2026, 11, 5)}, ai_test.SPEC_SHA256, mode="stop")
    assert mod.REAL_RUN_APPROVED is False and mod.REAL_INTERIM_APPROVED is True
