"""The Plan tab's live view of an AI run (webapp/live.py): the run's trades priced again from NSE's chain of now, with
where the index is against each trade's own levels. No LLM, nothing written, the run on file untouched; the price shown
is the price a Take gets. Mocked chains and a fixed IST clock (the ``world`` fixture); no network."""

import json
import shutil
from datetime import timedelta

import pytest

from tests.test_strategist import _q
from tests.test_take_honest_entry import at, chain
from tests.test_ui_regressions import render, text
from webapp import live, server, strategist as st, trade_record as tr

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to run the page's script")


def stamped(world, ch, seconds_old=20):
    return ch | {"timestamp": (world["clock"]["now"] - timedelta(seconds=seconds_old)).strftime("%d-%b-%Y %H:%M:%S")}


@pytest.mark.unit
def test_the_run_is_priced_again_from_the_chain_of_now_and_nothing_is_written(world):
    before = json.dumps(st.latest_run("NIFTY"), sort_keys=True)
    was = world["call"]["priced"]["legs"][0]["price"]
    world["live"]["chain"] = stamped(world, chain(22650, ce22600=_q(was + 30, was + 29.5, was + 30.5)))
    v = live.view("NIFTY")
    assert v["live"] and v["run_id"] == "run1" and v["spot"] == 22650 and v["spot_at_run"] == 22600 and v["age_s"] == 20
    assert v["as_of"] == "09:59:40" and len(v["trades"]) == 2
    call = v["trades"][0]
    assert call["status"] == "enter" and call["priced"]["legs"][0]["price"] == was + 30.5          # a buy pays the ask of now
    assert call["priced"]["outlay_per_lot"] == pytest.approx((was + 30.5) * 65)
    leg = call["levels"]["legs"][0]
    assert leg["premium_at_target"] > leg["price"] > leg["premium_at_stop"] and call["charges_per_lot"] > 0
    assert json.dumps(st.latest_run("NIFTY"), sort_keys=True) == before                          # the run stays fixed
    assert not tr.STORE.exists()                                                                # no trade, no refusal row
    json.dumps(v)                                                                               # the page gets it as JSON


@pytest.mark.unit
def test_the_live_price_is_the_price_a_take_gets(world):
    world["live"]["chain"] = stamped(world, chain(22640, ce22600=_q(200, 199.5, 201.25)))
    shown = live.view("NIFTY")["trades"][0]["priced"]["legs"][0]["price"]
    assert tr.take_from_run("run1", 0)["legs"][0]["entry"] == shown == 201.25


@pytest.mark.unit
def test_each_trade_says_where_the_index_is_against_its_own_levels(world):
    p = world["call"]["plan"]
    lo, hi, tgt, stop = (p[k] for k in ("underlying_entry_low", "underlying_entry_high", "underlying_target", "underlying_stop"))
    assert stop < lo < hi < tgt                                                                  # a bullish trade
    for spot, want in ((lo, "enter"), (hi, "enter"), (hi + 5, "ran"), (tgt - 5, "ran"), (tgt, "target"), (tgt + 50, "target"),
                       (lo - 5, "against"), (stop + 5, "against"), (stop, "stop"), (stop - 50, "stop")):
        world["live"]["chain"] = stamped(world, chain(spot))
        assert live.view("NIFTY")["trades"][0]["status"] == want, spot
    bear = {"underlying_entry_low": 100, "underlying_entry_high": 110, "underlying_target": 60, "underlying_stop": 130}
    assert [live.zone_status(bear, s) for s in (105, 90, 60, 120, 130)] == ["enter", "ran", "target", "against", "stop"]
    assert live.zone_status(bear | {"underlying_stop": None}, 105) is None
    assert live.zone_status(bear | {"underlying_stop": 50}, 105) is None                         # target and stop on one side


@pytest.mark.unit
def test_a_leg_with_no_live_quote_keeps_the_runs_prices_and_says_so(world):
    world["live"]["chain"] = stamped(world, chain(22600, ce22600=_q(150, 149, 0)))
    call, spread = live.view("NIFTY")["trades"]
    assert call == {"rank": call["rank"], "status": "unquoted", "priced": None, "levels": None, "charges_per_lot": None}
    assert spread["status"] == "unquoted" or spread["priced"]                                    # only trades holding that leg


@pytest.mark.unit
def test_nothing_is_live_without_a_run_of_today_an_open_market_and_fresh_quotes(world):
    world["live"]["chain"] = stamped(world, chain(), seconds_old=300)
    old = live.view("NIFTY")
    assert old["live"] is False and old["age_s"] == 300 and "300" in old["why"]
    world["live"]["chain"] = RuntimeError("NSE is down")
    assert live.view("NIFTY") == {"live": False, "symbol": "NIFTY", "why": "NSE chain unavailable: NSE is down"}
    world["live"]["chain"] = chain()
    world["clock"]["now"] = at(16, 0)
    assert live.view("NIFTY")["why"] == tr.MESSAGES["market_closed"]
    world["clock"]["now"] = at(10, 0, day=(2026, 11, 13))
    assert live.view("NIFTY")["why"] == tr.MESSAGES["run_expired"]
    assert live.view("BANKNIFTY")["live"] is False                                              # no run on file


@pytest.mark.unit
def test_the_endpoint_serves_the_live_view(world):
    world["live"]["chain"] = stamped(world, chain(22650))
    out = server.strategy_live("nifty")
    assert out["live"] and out["symbol"] == "NIFTY" and out["trades"][0]["status"] == "enter"


# ---------------------------------------------------------------- the page

def shown_run(world):
    return json.loads(json.dumps(world["run"] | {"considered": 2, "market_read": "up", "news_read": "", "agents": {}}, default=str))


@pytest.mark.unit
@needs_node
def test_the_page_shows_the_live_price_the_runs_price_and_the_status(world):
    was = world["call"]["priced"]["legs"][0]["price"]
    hi = world["call"]["plan"]["underlying_entry_high"]
    world["live"]["chain"] = stamped(world, chain(hi + 40, ce22600=_q(was + 30, was + 29.5, was + 30.5)))
    run, v = shown_run(world), live.view("NIFTY")
    page = text(render("S.strat.NIFTY = { result: ARGS[0] }; S.stratLive.NIFTY = ARGS[1]; aiListHtml('NIFTY', liveResult('NIFTY'))", run, v))
    assert f"limit {was + 30.5:,.2f}" in page and "Nikal gaya" in page and "Peeche mat bhaag" in page
    plain = text(render("aiListHtml('NIFTY', ARGS[0])", run))
    assert f"limit {was:,.2f}" in plain and "Nikal gaya" not in plain and "Zone mein" not in plain


@pytest.mark.unit
@needs_node
def test_the_budget_card_buys_at_the_live_price_and_says_what_the_run_showed(world):
    world["live"]["chain"] = stamped(world, chain(22610, ce22600=_q(120, 119.5, 120.5)))
    run, v = shown_run(world), live.view("NIFTY")
    card = text(render("budgetCardHtml('NIFTY', withLive(ARGS[0], ARGS[1]))", run, v))
    was = world["call"]["priced"]["legs"][0]["price"]
    assert "Buy at (live) ₹120.50 or less" in card and f"run ke time ₹{was:,.2f} tha" in card
    assert "Zone mein" in card and "Le sakta hai" in card and f"you pay ₹{120.5 * 65:,.2f}" in card


@pytest.mark.unit
@needs_node
def test_an_old_live_answer_or_one_for_another_run_is_not_shown(world):
    world["live"]["chain"] = stamped(world, chain(22610, ce22600=_q(120, 119.5, 120.5)))
    run, v = shown_run(world), live.view("NIFTY")
    for label, lv, now in (("another run", v | {"run_id": "other"}, 0), ("two minutes old", v | {"_got": 0}, 120001),
                           ("not live", {"live": False, "why": "x"}, 0)):
        out = render("JSON.stringify(withLive(ARGS[0], ARGS[1], ARGS[2]) === ARGS[0])", run, lv, now)
        assert out == "true", label
    assert render("JSON.stringify(withLive(ARGS[0], ARGS[1], ARGS[2])._live.spot)", run, v | {"_got": 0}, 119000) == "22610"


@pytest.mark.unit
@needs_node
def test_the_live_view_is_asked_for_with_the_chain_poll_and_never_for_a_closed_or_expired_run():
    ask = """var SENT = []; fetch = (p) => { SENT.push(p); return new Promise(() => {}); };
      S.strat.NIFTY = { result: ARGS[0] }; loadLiveTrades('NIFTY'); JSON.stringify(SENT)"""
    run = {"run_id": "r1", "trades": [{}]}
    assert json.loads(render(ask, run)) == ["/api/strategy/live/NIFTY"]
    for off in ({"expired": True}, {"market_closed": True}, {"trades": []}, {"run_id": None}):
        assert json.loads(render(ask, run | off)) == [], off
    poll = render("pollNseChains.toString()")
    assert "loadNseChain(sym).then(() => loadLiveTrades(sym))" in poll
