"""exit_allowed(): closing a trade asks only whether the market is open. Entry rules (the entry gate, any time window,
dedupe) never stop an exit: with the market open a trade can always be closed. With the market closed the exit is
refused with its own message, and a trade past expiry still settles at intrinsic value, by hand or by the monitor.
The monitor's auto-settle behaves exactly as before: market closed = no settle; expired = intrinsic."""

import inspect

import pytest

from tests.test_trade_record import RESULT, _q, chain
from webapp import trade_record as tr

PAST_STOP = (22750, _q(210, 209, 211), _q(145, 144, 146))                       # above the 22,720 stop
INSIDE = (22600, _q(130, 129, 131), _q(88, 87, 89))


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    state = {"open": True}
    monkeypatch.setattr(tr, "_market_open", lambda *a: state["open"])
    return state


@pytest.mark.unit
def test_with_the_market_open_a_trade_closes_even_when_the_entry_gate_refuses(market, monkeypatch):
    t = tr.take(RESULT)
    monkeypatch.setattr(tr, "entry_allowed", lambda: "outside the entry window (a stand-in for any entry rule)")
    c = tr.close(t["id"], chain(*INSIDE))
    assert c["status"] == "closed" and c["reason"] == "closed by you"


@pytest.mark.unit
def test_with_the_market_closed_a_close_is_refused_with_the_exit_message(market):
    t = tr.take(RESULT)
    market["open"] = False
    with pytest.raises(tr.TradeError, match="band karne ka asli price"):
        tr.close(t["id"], chain(*INSIDE))


@pytest.mark.unit
def test_a_trade_past_expiry_settles_with_the_market_closed_by_hand_and_by_the_monitor(market):
    by_hand = tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22650})
    by_monitor = tr.take(RESULT | {"expiry": "20-Oct-2026", "spot": 22660, "plan": RESULT["plan"] | {"underlying_target": 22470}},
                         confirm=True)                                           # a second bearish one: added to the bet on OK
    market["open"] = False
    assert tr.close(by_hand["id"])["reason"] == "expired"
    o = tr.refresh_open(lambda *a: pytest.fail("no chain after expiry"))
    assert any(t["id"] == by_monitor["id"] and t["reason"] == "expired" for t in o["closed"])


@pytest.mark.unit
def test_the_monitor_settles_with_the_market_open_and_not_with_it_closed(market):
    t = tr.take(RESULT)
    market["open"] = False
    o = tr.refresh_open(chain(*PAST_STOP))
    assert o["open"][0]["live"]["flags"] == [] and o["open"][0]["live"]["market_closed"] is True and o["stats"]["closed"] == 0
    market["open"] = True
    o = tr.refresh_open(chain(*PAST_STOP))
    assert o["closed"][0]["id"] == t["id"] and o["closed"][0]["reason"] == "stop reached"


@pytest.mark.unit
def test_exits_ask_exit_allowed_and_only_the_market_state():
    assert "exit_allowed()" in inspect.getsource(tr.close) and "entry_allowed()" not in inspect.getsource(tr.close)
    assert "exit_allowed()" in inspect.getsource(tr.overview) and "_market_open()" not in inspect.getsource(tr.overview)
    assert "exit_allowed()" in inspect.getsource(tr.refresh_open) and "_market_open()" not in inspect.getsource(tr.refresh_open)
    gate = inspect.getsource(tr.exit_allowed)
    assert "_market_open()" in gate and "entry_allowed" not in gate and "_same_bet" not in gate
