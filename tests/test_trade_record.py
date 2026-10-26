"""Trade Record: a dummy trade from the AI strategist is stored, marked at the close-out price, flagged (never
auto-closed) at the index target / stop, and closed with charges into a P&L history."""

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
def test_open_trade_is_marked_at_the_close_out_price_and_flagged_not_closed():
    tr.take(RESULT)
    # NIFTY at 22,470 (below the 22,480 target): buy back the sold call at the ask, sell the bought one at the bid
    o = tr.overview(chain(22470, _q(80, 79, 81), _q(58, 57, 59)))
    t = o["open"][0]
    assert t["live"]["pnl"] == pytest.approx(((132.45 - 81) + (57 - 89.95)) * 65)
    assert t["live"]["flags"] == ["target"] and t["status"] == "open" and o["stats"]["closed"] == 0
    again = tr.overview(chain(22600, _q(130, 129, 131), _q(88, 87, 89)))          # back up: the flag is remembered
    assert [a["kind"] for a in again["open"][0]["alerts"]] == ["target"] and again["open"][0]["live"]["flags"] == []


@pytest.mark.unit
def test_close_books_net_pnl_after_charges_and_updates_the_totals():
    t = tr.take(RESULT)
    tr.overview(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))               # stop reached
    c = tr.close(t["id"], chain(22750, _q(210, 209, 211), _q(145, 144, 146)))
    gross = ((132.45 - 211) + (144 - 89.95)) * 65
    assert c["status"] == "closed" and c["gross_pnl"] == pytest.approx(gross) and c["reason"] == "stop reached"
    assert c["charges"] > 4 * 20 and c["net_pnl"] == pytest.approx(gross - c["charges"])
    assert [x["exit"] for x in c["legs"]] == [211, 144]
    s = tr.overview()["stats"]
    assert (s["closed"], s["losses"], s["win_rate"]) == (1, 1, 0) and s["net"] == pytest.approx(c["net_pnl"])
    with pytest.raises(tr.TradeError):
        tr.close(t["id"])


@pytest.mark.unit
def test_after_expiry_the_trade_is_flagged_and_settles_at_intrinsic_value():
    t = tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22650})
    o = tr.overview(lambda *a: pytest.fail("no chain after expiry"))
    assert o["open"][0]["live"]["flags"] == ["expired"]
    c = tr.close(t["id"])
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
    # NIFTY at the target: the AI's suggestion settles itself; your trade is only flagged
    o = tr.overview(chain(22470, _q(80, 79, 81), _q(58, 57, 59)))
    assert o["ai"]["stats"]["closed"] == 1 and o["ai"]["closed"][0]["reason"] == "target reached"
    assert o["ai"]["closed"][0]["net_pnl"] > 0 and o["ai"]["by_score"]["Strong"]["wins"] == 1
    assert o["you"]["open"][0]["id"] == mine["id"] and o["stats"]["closed"] == 0           # page keys = your trades


@pytest.mark.unit
def test_ai_suggestion_settles_at_the_stop_and_at_expiry():
    tr.take(RESULT, source="ai")
    o = tr.overview(chain(22750, _q(210, 209, 211), _q(145, 144, 146)))         # above the 22,720 stop
    lost = o["ai"]["closed"][0]
    assert lost["reason"] == "stop reached" and lost["net_pnl"] < 0 and o["ai"]["stats"]["losses"] == 1
    tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22650}, source="ai")
    o = tr.overview()
    assert any(t["reason"] == "expired" for t in o["ai"]["closed"])


@pytest.mark.unit
def test_live_marks_carry_the_time_of_nses_snapshot():
    tr.take(RESULT)
    stamped = lambda s, e: chain(22600, _q(130, 129, 131), _q(88, 87, 89))(s, e) | {"timestamp": "26-Oct-2026 11:44:29"}  # noqa: E731
    assert tr.overview(stamped)["open"][0]["live"]["as_of"] == "26-Oct-2026 11:44:29"
