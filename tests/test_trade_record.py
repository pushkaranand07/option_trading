"""Trade Record: a dummy trade from the AI strategist is stored, marked at the close-out price, closed by itself at
the index target / stop (or by hand earlier) with charges into a P&L history."""

import pytest

from webapp import trade_record as tr


def _q(ltp, bid, ask):
    return {"ltp": ltp, "bid": bid, "ask": ask}


RESULT = {
    "symbol": "NIFTY", "expiry": "27-Oct-2099", "spot": 22600, "strategy_text": "x", "charges_per_lot": 90.0,
    "plan": {"strategy": "bear_call_spread", "bias": "bearish", "underlying_entry_low": 22580,
             "underlying_entry_high": 22640, "underlying_target": 22480, "underlying_stop": 22720},
    "priced": {"lot": 65, "net_per_unit": 42.5, "debit": False, "max_loss_per_lot": 3737.5, "max_profit_per_lot": 2762.5,
               "legs": [{"action": "SELL", "type": "CE", "strike": 22600.0, "price": 132.45, "id": "A"},
                        {"action": "BUY", "type": "CE", "strike": 22700.0, "price": 89.95, "id": "B"}]},
    "levels": {"legs": [{"action": "SELL", "type": "CE", "strike": 22600.0, "premium_at_target": 83.7, "premium_at_stop": 207.55},
                        {"action": "BUY", "type": "CE", "strike": 22700.0, "premium_at_target": 60.35, "premium_at_stop": 143.25}]},
}


def chain(spot, ce22600, ce22700):
    return lambda symbol, expiry: {"spot": spot, "rows": [{"strike": 22600.0, "ce": ce22600}, {"strike": 22700.0, "ce": ce22700}]}


@pytest.fixture(autouse=True)
def store(monkeypatch, tmp_path):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)       # the session is open (now and then) unless a test says not


@pytest.mark.unit
def test_take_records_one_lot_with_entry_and_premium_levels():
    t = tr.take(RESULT)
    assert t["status"] == "open" and t["lots"] == 1 and t["index_target"] == 22480
    assert [(x["entry"], x["target"], x["stop"]) for x in t["legs"]] == [(132.45, 83.7, 207.55), (89.95, 60.35, 143.25)]
    with pytest.raises(tr.TradeError):
        tr.take(RESULT | {"plan": RESULT["plan"] | {"strategy": "no_trade"}})
    with pytest.raises(tr.TradeError):
        tr.take(RESULT | {"rejected": ["naked"]})


@pytest.mark.unit
def test_open_trade_is_marked_at_the_close_out_price_and_closes_itself_at_the_target():
    tr.take(RESULT)
    # between target and stop: still open, marked at the close-out price (sold call at the ask, bought one at the bid)
    o = tr.overview(chain(22600, _q(130, 129, 131), _q(88, 87, 89)))
    t = o["open"][0]
    assert t["live"]["pnl"] == pytest.approx(((132.45 - 131) + (87 - 89.95)) * 65) and t["live"]["flags"] == []
    # NIFTY at 22,470 (below the 22,480 target): closed at those prices, into the history
    o = tr.refresh_open(chain(22470, _q(80, 79, 81), _q(58, 57, 59)))
    assert o["open"] == [] and o["stats"]["closed"] == 1
    c = o["closed"][0]
    assert c["reason"] == "target reached" and [x["exit"] for x in c["legs"]] == [81, 57] and c["spot_at_exit"] == 22470
    assert c["gross_pnl"] == pytest.approx(((132.45 - 81) + (57 - 89.95)) * 65) and c["net_pnl"] == pytest.approx(c["gross_pnl"] - c["charges"])


@pytest.mark.unit
def test_close_books_net_pnl_after_charges_and_updates_the_totals():
    t = tr.take(RESULT)
    c = tr.close(t["id"], chain(22650, _q(170, 169, 171), _q(115, 114, 116)))     # closed early by hand
    gross = ((132.45 - 171) + (114 - 89.95)) * 65
    assert c["status"] == "closed" and c["gross_pnl"] == pytest.approx(gross) and c["reason"] == "closed by you"
    assert c["charges"] > 4 * 20 and c["net_pnl"] == pytest.approx(gross - c["charges"])
    assert [x["exit"] for x in c["legs"]] == [171, 114]
    s = tr.overview()["stats"]
    assert (s["closed"], s["losses"], s["win_rate"]) == (1, 1, 0) and s["net"] == pytest.approx(c["net_pnl"])
    with pytest.raises(tr.TradeError):
        tr.close(t["id"])


@pytest.mark.unit
def test_after_expiry_the_trade_settles_itself_at_intrinsic_value():
    tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22650})
    o = tr.refresh_open(lambda *a: pytest.fail("no chain after expiry"))
    c = o["closed"][0]
    assert [x["exit"] for x in c["legs"]] == [50.0, 0.0] and c["reason"] == "expired"   # NIFTY 22,650 at expiry


@pytest.mark.unit
def test_remove_a_trade_taken_by_mistake():
    t = tr.take(RESULT)
    tr.delete(t["id"])
    assert tr.overview()["open"] == []
    with pytest.raises(tr.TradeError):
        tr.delete(t["id"])


@pytest.mark.unit
def test_ai_suggestions_settle_by_rule_and_are_scored_apart_from_your_trades():
    scored = RESULT | {"evidence": {"score": 80, "label": "Strong"}}
    tr.take(scored, source="ai")
    mine = tr.take(RESULT)
    # NIFTY at the target: both settle themselves, and are counted apart
    o = tr.refresh_open(chain(22470, _q(80, 79, 81), _q(58, 57, 59)))
    assert o["ai"]["stats"]["closed"] == 1 and o["ai"]["closed"][0]["reason"] == "target reached"
    assert o["ai"]["closed"][0]["net_pnl"] > 0 and o["ai"]["by_score"]["Strong"]["wins"] == 1
    assert o["you"]["closed"][0]["id"] == mine["id"] and o["stats"]["closed"] == 1           # page keys = your trades


@pytest.mark.unit
def test_ai_suggestion_settles_at_the_stop_and_at_expiry():
    tr.take(RESULT, source="ai")
    o = tr.refresh_open(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))         # above the 22,720 stop
    lost = o["ai"]["closed"][0]
    assert lost["reason"] == "stop reached" and lost["net_pnl"] < 0 and o["ai"]["stats"]["losses"] == 1
    tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22650}, source="ai")
    o = tr.refresh_open()
    assert any(t["reason"] == "expired" for t in o["ai"]["closed"])


@pytest.mark.unit
def test_your_trade_closes_itself_at_the_stop():
    tr.take(RESULT)
    o = tr.refresh_open(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))         # above the 22,720 stop
    c = o["closed"][0]
    assert c["reason"] == "stop reached" and [x["exit"] for x in c["legs"]] == [211, 144] and c["net_pnl"] < 0


LONG_CALL = {
    "symbol": "NIFTY", "expiry": "27-Oct-2099", "spot": 23800, "strategy_text": "x", "charges_per_lot": 45.0,
    "plan": {"strategy": "long_call", "bias": "bullish", "underlying_target": 24250, "underlying_stop": 23610},
    "priced": {"lot": 65, "net_per_unit": 140, "debit": True, "max_loss_per_lot": 9100, "max_profit_per_lot": None,
               "legs": [{"action": "BUY", "type": "CE", "strike": 23900.0, "price": 140.0, "id": "C"}]},
    "levels": {"legs": [{"action": "BUY", "type": "CE", "strike": 23900.0, "premium_at_target": 410, "premium_at_stop": 64}]},
}


def call_chain(spot, q):
    return lambda symbol, expiry: {"spot": spot, "rows": [{"strike": 23900.0, "ce": q}]}


@pytest.mark.unit
def test_premium_stop_closes_before_the_index_stop_like_a_dhan_super_order():
    tr.take(LONG_CALL)
    o = tr.overview(call_chain(23750, _q(70, 69, 71)))                          # index above its stop, premium above 64
    assert o["open"][0]["live"]["flags"] == []
    o = tr.refresh_open(call_chain(23750, _q(63.5, 63, 64)))                         # time decay: premium at the stop
    c = o["closed"][0]
    assert c["reason"] == "stop reached" and c["legs"][0]["exit"] == 63 and c["spot_at_exit"] == 23750
    t = tr.take(LONG_CALL, confirm=True)                                         # the same day, bullish: you said OK to the bet
    o = tr.refresh_open(call_chain(24000, _q(412, 411, 413)))                        # premium target before the index target
    assert next(x for x in o["closed"] if x["id"] == t["id"])["reason"] == "target reached"


@pytest.mark.unit
def test_debit_spread_has_no_premium_trigger_only_the_index():
    t = tr.take(RESULT | {"plan": RESULT["plan"] | {"strategy": "bear_put_spread"}})
    assert tr._super_legs(t) == []
    assert tr._super_legs(tr.take(RESULT, confirm=True)) == [0]                 # bearish again: added to the bet on OK                               # bear call spread: the sold leg


@pytest.mark.unit
def test_no_live_price_keeps_the_trade_open_until_there_is_one():
    tr.take(RESULT)
    o = tr.refresh_open(chain(22750, None, _q(145, 144, 146)))                     # stop reached, a leg has no quote
    assert o["open"][0]["live"]["flags"] == ["stop"] and o["stats"]["closed"] == 0
    o = tr.refresh_open(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))
    assert o["closed"][0]["reason"] == "stop reached"


@pytest.mark.unit
def test_live_marks_carry_the_time_of_nses_snapshot():
    tr.take(RESULT)
    stamped = lambda s, e: chain(22600, _q(130, 129, 131), _q(88, 87, 89))(s, e) | {"timestamp": "26-Oct-2026 11:44:29"}  # noqa: E731
    assert tr.overview(stamped)["open"][0]["live"]["as_of"] == "26-Oct-2026 11:44:29"


CONDOR_LEGS = [{"action": "BUY", "type": "PE", "strike": 22400.0, "price": 20.0, "id": "P1"},
               {"action": "SELL", "type": "PE", "strike": 22500.0, "price": 40.0, "id": "P2"},
               {"action": "SELL", "type": "CE", "strike": 22600.0, "price": 132.45, "id": "A"},
               {"action": "BUY", "type": "CE", "strike": 22700.0, "price": 89.95, "id": "B"}]
CONDOR = RESULT | {"plan": RESULT["plan"] | {"strategy": "iron_condor", "bias": "neutral", "underlying_target": 22550, "underlying_stop": 22400},
                   "priced": RESULT["priced"] | {"legs": CONDOR_LEGS}, "levels": {"legs": []}}


def condor_chain(spot):
    return lambda symbol, expiry: {"spot": spot, "rows": [
        {"strike": 22400.0, "pe": _q(18, 17, 19)}, {"strike": 22500.0, "pe": _q(35, 34, 36)},
        {"strike": 22600.0, "ce": _q(130, 129, 131)}, {"strike": 22700.0, "ce": _q(88, 87, 89)}]}


@pytest.mark.unit
def test_an_iron_condor_is_held_inside_its_sold_strikes_and_closed_when_the_index_leaves_them():
    t = tr.take(CONDOR, source="ai")
    assert t["range"] == [22500.0, 22600.0] and t["index_target"] is None and t["index_stop"] is None
    o = tr.refresh_open(condor_chain(22560))                                         # above the AI's "target" 22,550: still open
    assert o["ai"]["open"] and o["ai"]["open"][0]["live"]["flags"] == []
    o = tr.refresh_open(condor_chain(22610))                                         # above the sold call: the range is broken
    c = o["ai"]["closed"][0]
    assert c["reason"] == "range broken" and [x["exit"] for x in c["legs"]] == [17, 36, 131, 87]


@pytest.mark.unit
def test_a_condor_closed_by_the_old_directional_rule_is_reopened_once():
    import json

    t = tr.take(CONDOR, source="ai")
    rows = json.loads(tr.STORE.read_text(encoding="utf-8"))                     # as the old rule left it
    for r in rows:
        r.pop("range"); r.update(index_target=22550, index_stop=22400, status="closed", reason="target reached", closed_at="x", net_pnl=-275.0)
        for leg in r["legs"]:
            leg["exit"] = leg["entry"]
    tr.STORE.write_text(json.dumps(rows), encoding="utf-8")
    o = tr.refresh_open(condor_chain(22560))
    again = o["ai"]["open"][0]
    assert again["id"] == t["id"] and again["range"] == [22500.0, 22600.0] and "net_pnl" not in again and "bug" in again["note"]
    assert all("exit" not in x for x in again["legs"]) and o["ai"]["stats"]["closed"] == 0
    rows = json.loads(tr.STORE.read_text(encoding="utf-8"))
    rows[0].update(status="closed", reason="closed by you", closed_at="y", net_pnl=10.0)                   # a later, real exit is never undone
    tr.STORE.write_text(json.dumps(rows), encoding="utf-8")
    assert tr.overview(condor_chain(22560))["ai"]["stats"]["closed"] == 1


@pytest.mark.unit
def test_a_closed_market_shows_the_last_prices_but_never_enters_closes_or_settles():
    t = tr.take(RESULT)
    tr._market_open = lambda *a: False                                           # restored by the fixture
    o = tr.refresh_open(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))         # past the stop, after 15:30
    v = o["open"][0]["live"]
    assert o["stats"]["closed"] == 0 and v["market_closed"] and v["flags"] == [] and v["pnl"] is not None
    with pytest.raises(tr.TradeError, match="Market band"):
        tr.take(RESULT)
    with pytest.raises(tr.TradeError, match="Market band"):
        tr.close(t["id"], chain(22750, _q(210, 209, 211), _q(145, 144, 146)))
    tr._market_open = lambda *a: True
    assert tr.refresh_open(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))["closed"][0]["reason"] == "stop reached"


@pytest.mark.unit
def test_the_same_ai_trade_from_a_re_run_is_recorded_once_yours_are_not_merged():
    a = tr.take(RESULT, source="ai")
    assert tr.take(RESULT, source="ai")["id"] == a["id"]
    tr.take(RESULT)
    tr.take(RESULT, confirm=True)                                               # your second: asked first, then its own row
    o = tr.overview(chain(22600, _q(130, 129, 131), _q(88, 87, 89)))
    assert len(o["ai"]["open"]) == 1 and len(o["you"]["open"]) == 2
