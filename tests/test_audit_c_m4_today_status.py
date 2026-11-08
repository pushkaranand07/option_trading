"""Audit M4 (support): ai_test.today_status() feeds the Plan page and must never raise. A missing or changed spec, a
registry row from an older format, an unreadable line or a failing source lookup gives state ERROR with a short
reason, and the exception is logged."""

import json
import logging
from datetime import datetime

import pytest
import pytz

from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import ai_test, signals

IST = pytz.timezone("Asia/Kolkata")
NOW = IST.localize(datetime(2026, 11, 12, 11, 0))                    # a v3 session (Thursday)


@pytest.fixture
def reg(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_test, "REGISTRY", tmp_path / "v3.jsonl")
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    return tmp_path / "v3.jsonl"


def _is_error(s):
    assert s["state"] == "ERROR" and s["reason"] and len(s["reason"]) <= 300
    assert s["version"] == ai_test.VERSION and s["day"] == "2026-11-12" and "fingerprint_problem" in s


@pytest.mark.unit
def test_a_missing_spec_is_an_error_state_not_an_exception(reg, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(ai_test, "SPEC_FILE", tmp_path / "missing.json")
    with caplog.at_level(logging.ERROR, logger=ai_test.logger.name):
        s = ai_test.today_status(NOW)
    _is_error(s)
    assert "FileNotFoundError" in s["reason"] and any(r.exc_info for r in caplog.records)


@pytest.mark.unit
def test_an_old_registry_row_without_a_timestamp_is_an_error_state(reg, monkeypatch):
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: None)
    row = {"type": "strategist", "date": "2026-11-12", "spec_hash": ai_test.SPEC_SHA256, "outcome": "trade"}    # no timestamp
    reg.write_text(json.dumps(row) + "\n", encoding="utf-8")
    s = ai_test.today_status(NOW)
    _is_error(s)
    assert "KeyError" in s["reason"] and s["fingerprint_problem"] is None


@pytest.mark.unit
def test_an_unreadable_registry_line_is_an_error_state(reg, monkeypatch):
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: None)
    reg.write_text("{not json\n", encoding="utf-8")
    _is_error(ai_test.today_status(NOW))


@pytest.mark.unit
def test_a_failing_source_lookup_is_an_error_state(reg, monkeypatch):
    def boom():
        raise OSError("could not get source code")

    monkeypatch.setattr(ai_test, "prompt_fingerprint", boom)
    s = ai_test.today_status(NOW)
    _is_error(s)
    assert "OSError" in s["reason"]


@pytest.mark.unit
def test_a_healthy_registry_still_gives_its_normal_answer(reg, monkeypatch):
    monkeypatch.setattr(ai_test, "fingerprint_problem", lambda: None)
    assert ai_test.today_status(NOW)["state"] == "NOT YET"
