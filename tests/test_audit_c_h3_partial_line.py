"""Audit H3 follow-up: readers take no lock, so one can see an append half-written. Every append ends with a newline,
so a final line without one is a write in progress: ``read`` leaves it out instead of failing."""

from datetime import date, datetime

import pytest
import pytz

from tradingagents.research import registry

IST = pytz.timezone("Asia/Kolkata")


def _two_rows(path):
    for day in (date(2027, 1, 4), date(2027, 1, 5)):
        registry.register_structure(path, day=day, symbol="NIFTY", expiry="x", spec_hash="s", now=IST.localize(datetime(day.year, day.month, day.day, 10)),
                                    outcome="no_trade", structure=None, direction=None, legs=[], max_risk_indicative=None)


@pytest.mark.unit
def test_a_half_written_last_line_is_left_out(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    whole = registry.read(path)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"type": "strategist", "date": "2027-01-0')                     # an append caught mid-write
    assert registry.read(path) == whole
    assert registry.verify(path) == 2


@pytest.mark.unit
def test_a_bad_complete_line_still_fails(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("{not json\n")                                                    # finished, but corrupt: not hidden
    with pytest.raises(ValueError):
        registry.read(path)
