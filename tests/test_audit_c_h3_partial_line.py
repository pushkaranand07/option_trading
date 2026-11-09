"""Audit H3 follow-up: a registry whose last line has no newline.

Every append ends with a newline. A reader that takes no lock (today_status, ai_settle, trade_record) may see an append
half-written: its lenient ``read`` leaves that final line out instead of failing. Anything done while holding the lock
(verify, every check-then-append, ai_test.record) is strict: no append can be in progress then, so an unterminated last
line is a crash leftover or an edit, and it is refused untouched, never appended to or hidden."""

from datetime import date, datetime

import pytest
import pytz

from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from tradingagents.research import registry
from webapp import ai_test, signals

IST = pytz.timezone("Asia/Kolkata")
DAYS = (date(2027, 1, 4), date(2027, 1, 5))


def _structure(path, day):
    return registry.register_structure(path, day=day, symbol="NIFTY", expiry="x", spec_hash="s", now=IST.localize(datetime(day.year, day.month, day.day, 10)),
                                       outcome="no_trade", structure=None, direction=None, legs=[], max_risk_indicative=None)


def _two_rows(path):
    for day in DAYS:
        _structure(path, day)


def _half_write(path):
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write('{"type": "strategist", "date": "2027-01-0')                     # an append caught mid-write


@pytest.mark.unit
def test_a_lenient_read_leaves_out_an_append_in_progress(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    whole = registry.read(path)
    _half_write(path)
    assert registry.read(path) == whole


@pytest.mark.unit
def test_a_strict_read_and_verify_refuse_an_unterminated_last_line(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    _half_write(path)
    with pytest.raises(registry.RegistryError, match="unterminated final line"):
        registry.read(path, strict=True)
    with pytest.raises(registry.RegistryError, match="unterminated final line"):
        registry.verify(path)


@pytest.mark.unit
def test_an_append_after_a_partial_line_is_refused_and_the_file_is_untouched(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    _half_write(path)
    before = path.read_bytes()
    with pytest.raises(registry.RegistryError, match="unterminated final line"):
        _structure(path, date(2027, 1, 6))
    with pytest.raises(registry.RegistryError, match="unterminated final line"):
        registry._append(path, {"type": "missed", "date": "2027-01-06", "spec_hash": "s"})
    assert path.read_bytes() == before


@pytest.mark.unit
def test_a_real_last_row_without_its_newline_is_not_hidden_from_a_duplicate_check(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))                            # restored or hand-edited
    before = path.read_bytes()
    with pytest.raises(registry.RegistryError, match="unterminated final line"):
        _structure(path, DAYS[1])                                                 # the same day again
    assert path.read_bytes() == before


@pytest.mark.unit
def test_an_edited_last_row_with_its_newline_stripped_fails_verify(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    first, last = path.read_bytes().rstrip(b"\n").split(b"\n")
    path.write_bytes(first + b"\n" + last.replace(b'"no_trade"', b'"trade"'))  # only the last row edited, no newline
    with pytest.raises(registry.RegistryError):
        registry.verify(path)


@pytest.mark.unit
def test_a_bad_complete_line_still_fails(tmp_path):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("{not json\n")                                                    # finished, but corrupt: not hidden
    with pytest.raises(ValueError):
        registry.read(path)


@pytest.mark.unit
def test_record_refuses_a_partial_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "r.jsonl"
    _two_rows(path)
    _half_write(path)
    before = path.read_bytes()
    monkeypatch.setattr(ai_test, "prompt_fingerprint", lambda: "fp")
    monkeypatch.setattr(ai_test, "model_settings", lambda: {"m": 1})
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    spec = {"version": {"prompt_sha256": "fp", "model": {"m": 1}}}
    now = IST.localize(datetime(2027, 1, 7, 10))
    with pytest.raises(registry.RegistryError, match="unterminated final line"):
        ai_test.record({"symbol": "NIFTY", "expiry": "x", "plan": {"strategy": "no_trade"}}, path, tmp_path / "c", now, spec=spec)
    assert path.read_bytes() == before


@pytest.mark.unit
def test_today_status_on_a_partial_file_never_raises(tmp_path, monkeypatch):
    path = tmp_path / "v3.jsonl"
    monkeypatch.setattr(ai_test, "REGISTRY", path)
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: None)
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    _half_write(path)
    s = ai_test.today_status(IST.localize(datetime(2026, 11, 12, 11)))
    assert s["state"] in ("NOT YET", "ERROR")
