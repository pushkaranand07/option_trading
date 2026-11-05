"""The trade record reads "is the market open?" from one function, _market_open(at=None), for now (the gates) and for a
past moment (a row entered outside the session). It used to read the second from the real calendar directly, so a
trade the gate let in was dropped from the stats whenever the suite ran after 15:30 (seven tests failed only then)."""

from datetime import datetime

import pytest
import pytz
import time_machine

from tests.test_trade_record import RESULT, _q, chain
from webapp import trade_record as tr

IST = pytz.timezone("Asia/Kolkata")
PAST_STOP = (22750, _q(210, 209, 211), _q(145, 144, 146))


@pytest.mark.unit
@pytest.mark.parametrize("hour", [10, 20])
def test_a_trade_the_gate_let_in_is_counted_at_any_wall_clock_hour(tmp_path, monkeypatch, hour):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)                    # the session, for now and for any moment
    with time_machine.travel(IST.localize(datetime(2026, 11, 5, hour, 0)), tick=False):
        tr.take(RESULT)
        o = tr.overview(chain(*PAST_STOP))
    assert (o["stats"]["closed"], o["stats"]["losses"]) == (1, 1), hour


@pytest.mark.unit
def test_entry_exit_and_the_past_moment_all_read_the_same_function():
    import inspect
    assert "_market_open(when)" in inspect.getsource(tr._outside_session)
    assert "signals.market_open" not in inspect.getsource(tr._outside_session)


@pytest.mark.unit
def test_row_times_and_expiry_read_the_same_clock_as_the_session(monkeypatch):
    from webapp import signals
    monkeypatch.setattr(signals, "now_ist", lambda: IST.localize(datetime(2026, 11, 5, 10, 0)))
    with time_machine.travel(IST.localize(datetime(2026, 11, 5, 20, 0)), tick=False):   # the wall clock says otherwise
        assert tr._now() == "2026-11-05 10:00"
        assert tr._expired({"expiry": "05-Nov-2026"}) is False                       # 10:00 on expiry day: not yet
