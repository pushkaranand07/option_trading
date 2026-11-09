"""Audit step 2: every trade records where it came from; the CSV carries it with the source; the Trade Record keeps
"AI #1" and "My picks" apart, with their own stats; AI #1 rows link to the v2 registry of their day. Old trades
without these fields show "unknown" and are never back-filled."""

import csv
import io
from datetime import date

import pytest

from tests.test_take_honest_entry import at, chain, take, world  # noqa: F401  (world is a fixture)
from tests.test_ui_regressions import app_source
from tradingagents.research import registry
from webapp import ai_test, strategist as st, trade_record as tr

HEADER = ["view", "source", "status", "taken_at", "closed_at", "symbol", "strategy", "expiry", "legs", "run_id", "candidate",
          "ai_rank", "mode", "run_asked_at", "research_source", "spot_at_run", "spot_at_take", "in_entry_zone", "quote_age_s", "attempts",
          "index_target", "index_stop", "close_reason", "refusal_reason", "is_v2_counted", "v2_entry", "gross_pnl",
          "charges", "net_pnl", "ai_reason"]
APP = app_source()                              # the page's script: every module under webapp/static/js


@pytest.fixture
def prov(world, tmp_path, monkeypatch):
    run = world["run"] | {"mode": "quick", "agents": {"source": "complete analysis", "at": "09:05", "rating": "Hold"}}
    for i, c in enumerate(run["trades"]):
        c["rank"] = i + 1
    st.save_run(run)
    monkeypatch.setattr(ai_test, "REGISTRY", tmp_path / "v2.jsonl")
    return world


def rows():
    return list(csv.reader(io.StringIO(tr.history_csv())))


@pytest.mark.unit
def test_a_new_trade_stores_its_provenance(prov):
    t = take(prov).json()
    assert (t["mode"], t["ai_rank"], t["research_source"], t["in_entry_zone"]) == ("quick", 1, "complete analysis", True)
    assert t["run_id"] == "run1" and t["candidate"] == 0 and t["spot_at_run"] == 22600 and t["spot_at_entry"] == 22600


@pytest.mark.unit
def test_the_csv_has_the_header_and_a_sample_row(prov):
    take(prov, candidate=1)
    head, *body = rows()
    assert head == HEADER
    r = dict(zip(head, body[0], strict=True))
    assert (r["view"], r["source"], r["status"], r["run_id"], r["candidate"], r["ai_rank"], r["mode"]) == ("My picks", "you", "open", "run1", "1", "2", "Quick")
    assert (r["research_source"], r["in_entry_zone"], r["spot_at_take"], r["is_v2_counted"]) == ("complete analysis", "yes", "22600", "no")
    assert "shown" in r["legs"] and "entry" in r["legs"] and r["refusal_reason"] == "" and r["close_reason"] == ""


@pytest.mark.unit
def test_an_old_trade_without_the_fields_loads_shows_unknown_and_sits_in_my_picks(prov):
    old = {"id": "old1", "taken_at": "2026-11-04 11:27", "status": "closed", "lots": 1, "symbol": "NIFTY", "expiry": "09-Nov-2026",
           "lot": 65, "strategy": "long_call", "legs": [{"action": "BUY", "type": "CE", "strike": 23900.0, "entry": 140.15, "exit": 165.7}],
           "spot_at_entry": 23823, "closed_at": "2026-11-04 13:56", "reason": "closed by you", "gross_pnl": 1661.0, "charges": 72.0,
           "net_pnl": 1589.0, "alerts": []}                                         # no source, no run id, no provenance
    tr._save([old])
    o = tr.overview(lambda *a: chain())
    assert [t["id"] for t in o["you"]["closed"]] == ["old1"] and not o["ai"]["closed"]
    r = dict(zip(HEADER, rows()[1], strict=True))
    assert r["view"] == "My picks" and r["source"] == "unknown"
    for k in ("run_id", "candidate", "ai_rank", "mode", "run_asked_at", "research_source", "spot_at_run", "spot_at_take", "in_entry_zone"):
        assert r[k] == "unknown", k
    assert r["is_v2_counted"] == "no" and r["net_pnl"] == "1589.00"


@pytest.mark.unit
def test_the_two_views_keep_their_own_stats(prov):
    base = {"lots": 1, "symbol": "NIFTY", "expiry": "09-Nov-2026", "lot": 65, "strategy": "long_call", "alerts": [],
            "legs": [{"action": "BUY", "type": "CE", "strike": 23900.0, "entry": 100.0, "exit": 110.0}], "status": "closed",
            "taken_at": "2026-11-05 10:00", "closed_at": "2026-11-05 11:00", "reason": "target reached", "gross_pnl": 1.0, "charges": 0.0}
    tr._save([base | {"id": "a", "source": "ai", "net_pnl": 500.0}, base | {"id": "b", "source": "you", "net_pnl": -200.0}])
    o = tr.overview(lambda *a: chain())
    assert (o["ai"]["stats"]["net"], o["ai"]["stats"]["wins"], o["ai"]["stats"]["losses"]) == (500.0, 1, 0)
    assert (o["you"]["stats"]["net"], o["you"]["stats"]["wins"], o["you"]["stats"]["losses"]) == (-200.0, 0, 1)


@pytest.mark.unit
def test_a_not_taken_pick_is_listed_and_in_the_csv_but_not_counted(prov):
    prov["live"]["chain"] = chain(spot=prov["call"]["plan"]["underlying_entry_high"] + 30)
    tr.record_ai_pick("run1")
    o = tr.overview(lambda *a: chain())
    assert len(o["ai"]["not_taken"]) == 1 and o["ai"]["stats"]["open"] == 0 and o["ai"]["stats"]["closed"] == 0
    [r] = [dict(zip(HEADER, x, strict=True)) for x in rows()[1:]]
    assert (r["view"], r["status"], r["in_entry_zone"], r["ai_rank"], r["mode"]) == ("AI #1", "not_taken", "no", "1", "Quick")
    assert "entry zone" in r["refusal_reason"] and r["spot_at_take"] != "unknown"


def _register(day, legs, priced, hour=10):
    now = at(hour, 0, day=(day.year, day.month, day.day))
    row = registry.register_structure(ai_test.REGISTRY, day=day, symbol="NIFTY", expiry="27-Nov-2026", spec_hash=ai_test.SPEC_SHA256,
                                      now=now, outcome="trade", structure="long_call", direction="bullish", legs=legs, max_risk_indicative=1.0)
    registry.record_entry(ai_test.REGISTRY, registration=row["hash"], now=now, status="entered", legs=priced, spot=22600)


@pytest.mark.unit
def test_an_ai_1_row_shows_whether_v2_counted_it_and_v2s_entry(prov):
    tr.record_ai_pick("run1")                                                      # AI #1: BUY 22600 CE, on 2026-11-12
    _register(date(2026, 11, 12), [{"action": "BUY", "type": "CE", "strike": 22600.0}],
              [{"action": "BUY", "type": "CE", "strike": 22600.0, "price": 102.5}])
    o = tr.overview(lambda *a: chain())
    v2 = o["ai"]["open"][0]["v2"]
    assert v2["registered_that_day"] and v2["same_trade"] and v2["counted"] and v2["entry"] == "B 22600 CE 102.50"
    assert o["ai"]["v2_stats"]["open"] == 1
    r = dict(zip(HEADER, rows()[1], strict=True))
    assert r["is_v2_counted"] == "yes" and r["v2_entry"] == "B 22600 CE 102.50"


@pytest.mark.unit
def test_v2_counting_a_different_trade_or_a_pre_start_day_is_not_counted(prov):
    tr.record_ai_pick("run1")
    _register(date(2026, 11, 12), [{"action": "BUY", "type": "CE", "strike": 22700.0}],
              [{"action": "BUY", "type": "CE", "strike": 22700.0, "price": 55.0}])
    v2 = tr.overview(lambda *a: chain())["ai"]["open"][0]["v2"]
    assert v2["registered_that_day"] and not v2["same_trade"] and not v2["counted"]
    assert tr._v2_link({"source": "ai", "taken_at": "2026-11-06 12:58", "strategy": "x", "legs": []}, {})["note"] == "before v3 started (2026-11-09)"


@pytest.mark.unit
def test_the_trade_record_page_has_two_views_and_downloads_the_server_csv():
    assert "My picks" in APP and "AI #1" in APP and '"/api/trades.csv"' in APP
    view = APP[APP.index("function viewHtml("):]
    assert "v.v2_stats" in view[:view.index("\n}\n")] and "v2Txt(t)" in APP[APP.index("const tradeCell = "):][:500]
    assert "t.v2.counted" in APP[APP.index("const v2Txt"):][:300]
