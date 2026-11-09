"""Audit L6 (trade_record part): every time the trade record writes is India time, whatever timezone the PC runs in.
events.log used the PC's naive ``datetime.now()``; on a PC set to UTC its lines were 5:30 behind the rows they
describe. Simulated here by making trade_record's ``datetime.now()`` answer as a UTC machine would."""

from datetime import datetime

import pytest
import pytz
import time_machine

from webapp import trade_record as tr

IST = pytz.timezone("Asia/Kolkata")
AT = IST.localize(datetime(2026, 11, 5, 10, 0, 7))


class UtcMachine(datetime):
    """datetime as on a PC set to UTC: a naive now() is UTC wall time; an aware now(tz) is unchanged."""

    @classmethod
    def now(cls, tz=None):
        return AT.astimezone(pytz.utc).replace(tzinfo=None) if tz is None else AT.astimezone(tz)


@pytest.fixture
def utc_pc(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "datetime", UtcMachine)
    with time_machine.travel(AT, tick=False):
        yield


@pytest.mark.unit
def test_events_log_is_stamped_in_ist_on_a_utc_machine(utc_pc):
    tr._event("taken", {"id": "abc", "strategy": "long_call", "symbol": "NIFTY", "expiry": "27-Nov-2099"})
    line = (tr.STORE.parent / "events.log").read_text(encoding="utf-8").splitlines()[-1]
    assert line.startswith("2026-11-05 10:00:07 abc "), line


@pytest.mark.unit
def test_row_times_stay_ist_on_a_utc_machine(utc_pc):
    assert tr._now() == "2026-11-05 10:00"
    assert tr._expired({"expiry": "05-Nov-2026"}) is False


@pytest.mark.unit
def test_no_naive_clock_is_left_in_trade_record():
    import inspect
    src = inspect.getsource(tr)
    assert "datetime.now()" not in src and "date.today()" not in src
