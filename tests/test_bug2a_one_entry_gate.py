"""Bug 2(a): whether a trade may be entered now is decided in one place, trade_record.entry_allowed(), and every entry
path asks it: take() (the only writer of a trade row), take_from_run() before it fetches prices, and the AI run in
strategist.start() before it records its pick. (The 15:33 row was written by an AI path that had no such check.)"""

import inspect

import pytest

from tests.test_step1c_ai_auto_take import ai_rows, run_ai  # noqa: F401  (fixtures)
from tests.test_take_honest_entry import CHAIN, take, world  # noqa: F401
from webapp import signals, strategist as st, trade_record as tr

REASON = "the session gate says no (test)"


@pytest.fixture
def gate_says_no(monkeypatch):
    monkeypatch.setattr(signals, "market_open", lambda *a, **k: True)          # the calendar alone would say yes
    monkeypatch.setattr(tr, "entry_allowed", lambda: REASON, raising=False)


@pytest.mark.unit
def test_take_refuses_through_the_gate(world, gate_says_no):
    with pytest.raises(tr.TradeError, match="test"):
        tr.take(world["call"] | {"symbol": "NIFTY", "expiry": "27-Nov-2026"}, source="you")


@pytest.mark.unit
def test_your_take_refuses_through_the_gate_before_fetching_prices(world, gate_says_no, monkeypatch):
    from webapp import option_chain as oc

    monkeypatch.setattr(oc, "chain", lambda *a, **k: pytest.fail("prices were fetched for a refused Take"))
    r = take(world)
    assert r.status_code == 400 and REASON in r.json()["detail"]


@pytest.mark.unit
def test_the_ai_run_asks_the_same_gate_before_recording_its_pick(world, run_ai, gate_says_no):
    j = run_ai()
    assert j["status"] == "done" and j["result"]["market_closed"] is True
    assert ai_rows() == []                                                       # nothing recorded, not even as not taken


@pytest.mark.unit
def test_the_session_is_read_in_one_place():
    src = inspect.getsource(tr)
    assert src.count("_market_open()") == 3                                      # its definition, entry_allowed(), the live marking
    for fn in (tr.take, tr.take_from_run, tr.close):
        assert "entry_allowed()" in inspect.getsource(fn), fn.__name__
    start = inspect.getsource(st.start)
    assert "entry_allowed()" in start and "market_open()" not in start
