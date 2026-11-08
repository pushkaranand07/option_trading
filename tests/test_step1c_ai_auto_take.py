"""Audit step 1c: the AI's #1 goes into the AI track record through the same fresh-chain path as your Take (fresh
chain, bid / ask, stale-quote and entry-zone checks), after the ranking; a refused pick is kept as "not taken" with
its reason. The real start() runs with the LLM step replaced; the v2 registry is replaced too (its own path)."""

import time

import pytest

from tests.test_take_honest_entry import _q, chain, world  # noqa: F401  (world is a fixture)
from webapp import ai_test, server, strategist as st, trade_record as tr

APP = (__import__("pathlib").Path(server.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")


@pytest.fixture
def run_ai(world, monkeypatch):
    """Run start() to the end with the ranking replaced by the fixture's run (its prices are the run's)."""
    monkeypatch.setattr(st, "agents_view", lambda symbol: {"rating": "Hold", "decision": "d"})
    monkeypatch.setattr(st, "save_research", lambda symbol, r, day=None: r)
    monkeypatch.setattr(ai_test, "record", lambda *a, **k: None)
    ranked = {k: v for k, v in world["run"].items() if k not in ("run_id", "day")}
    monkeypatch.setattr(st, "ai_ranked", lambda *a, **k: dict(ranked, trades=list(ranked["trades"])))

    def go():
        job = st.start("NIFTY", mode="full")
        for _ in range(200):
            j = st.job(job)
            if j["status"] != "running":
                return j
            time.sleep(0.02)
        raise AssertionError("the run did not finish")
    return go


def ai_rows():
    return [t for t in tr._load() if t.get("source") == "ai"]


@pytest.mark.unit
def test_the_ais_pick_is_priced_from_a_fresh_chain_after_the_ranking(world, run_ai):
    world["live"]["chain"] = chain(ce22600=_q(104, 103, 106))                  # the ask moved 101 -> 106 during the ranking
    j = run_ai()
    assert j["status"] == "done", j
    [t] = ai_rows()
    assert t["status"] == "open" and t["legs"][0]["entry"] == 106 and t["legs"][0]["shown_price"] == 101
    assert t["run_id"] == j["result"]["run_id"] and t["candidate"] == 0 and j["result"]["ai_record"] == t["id"]


@pytest.mark.unit
def test_a_pick_outside_its_entry_zone_is_kept_as_not_taken_with_the_reason(world, run_ai):
    hi = world["call"]["plan"]["underlying_entry_high"]
    world["live"]["chain"] = chain(spot=hi + 30)
    j = run_ai()
    [t] = ai_rows()
    assert t["status"] == "not_taken" and "entry zone" in t["reason"]
    assert "entry zone" in j["result"]["ai_record_refused"]
    o = tr.overview(lambda *a: chain())
    assert o["ai"]["stats"]["open"] == 0 and o["ai"]["stats"]["closed"] == 0 and len(o["ai"]["not_taken"]) == 1


@pytest.mark.unit
def test_a_pick_with_stale_quotes_is_kept_as_not_taken(world, run_ai):
    world["live"]["chain"] = chain() | {"timestamp": "12-Nov-2026 09:57:00"}       # 3 minutes old at 10:00
    run_ai()
    [t] = ai_rows()
    assert t["status"] == "not_taken" and "s old" in t["reason"]


@pytest.mark.unit
def test_a_pick_with_no_live_quote_is_kept_as_not_taken(world, run_ai):
    world["live"]["chain"] = chain(ce22600=_q(100, 0, 101))
    run_ai()
    [t] = ai_rows()
    assert t["status"] == "not_taken" and "bid / ask" in t["reason"]


@pytest.mark.unit
def test_the_page_lists_the_not_taken_picks_with_their_reason():
    ai = APP[APP.index("function viewHtml("):]                               # since the redesign: one view builder for both
    ai = ai[:ai.index("\n}\n")]
    rows = APP[APP.index("function notTakenRowsHtml("):]                     # since step 3: one builder for every not-taken row
    rows = rows[:rows.index("\n}\n")]
    assert "notTakenRowsHtml(v.not_taken)" in ai and "not taken" in rows and "t.reason" in rows
