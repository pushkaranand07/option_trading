"""Audit L6 (Track C files): the times shown for a plan suggestion, a strategist job and the morning plan are India
time, whatever timezone the PC runs in. Only non-fingerprinted code changed: the date-keyed files that fingerprinted
code reads (save_research, morning.build's day, morning.load) are left as they are."""

import time
from datetime import datetime

import pytest
import pytz

from webapp import ai_test, morning, strategist as st

IST = pytz.timezone("Asia/Kolkata")
FIXED = IST.localize(datetime(2026, 11, 12, 3, 7, 9))               # 03:07 IST: 21:37 the day before in UTC


@pytest.fixture
def ist_clock(monkeypatch):
    monkeypatch.setattr(st, "now_ist", lambda: FIXED, raising=False)
    monkeypatch.setattr(morning, "now_ist", lambda: FIXED, raising=False)


class _Plan:
    strategy = "no_trade"

    def model_dump(self):
        return {"strategy": "no_trade"}


@pytest.mark.unit
def test_a_plan_suggestion_is_stamped_in_india_time(ist_clock, monkeypatch):
    monkeypatch.setattr(st, "build_context", lambda s, e: ({}, {"expiry": "x", "spot": 1.0, "lot": 65, "summary": {}}))
    monkeypatch.setattr(st, "check_structure", lambda plan, ch: [])
    monkeypatch.setattr(st, "warnings", lambda plan, priced: [])
    monkeypatch.setattr(st, "evidence", lambda plan, ctx, priced: None)
    out = st.recommend("NIFTY", llm=lambda ctx, problems=None: _Plan())
    assert out["asked_at"] == "2026-11-12 03:07" and out["seconds"] == 0


@pytest.mark.unit
def test_a_strategist_job_starts_in_india_time(ist_clock, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no ranking in this test")

    monkeypatch.setattr(st, "ai_ranked", boom)
    monkeypatch.setattr(ai_test, "record", lambda *a, **k: None)
    job_id = st.start("NIFTY")
    for _ in range(200):
        if st.job(job_id)["status"] != "running":
            break
        time.sleep(0.05)
    assert st.job(job_id)["started"] == "03:07:09"


@pytest.mark.unit
def test_the_morning_plan_is_stamped_in_india_time(ist_clock, monkeypatch):
    monkeypatch.setattr(morning, "session", lambda day, calendar=None: {"trading": False})
    monkeypatch.setattr(morning, "context", lambda s, day: {})
    monkeypatch.setattr(morning, "load", lambda day=None: None)
    monkeypatch.setattr(morning, "save", lambda plan, day: None)
    assert morning.build(with_ai=False)["built_at"] == "2026-11-12 03:07"


@pytest.mark.unit
def test_the_morning_ai_job_starts_in_india_time(ist_clock, monkeypatch):
    monkeypatch.setattr(morning, "build", lambda **k: None)
    monkeypatch.setattr(morning, "_ai_job", {"running": False, "started": None, "error": None})
    assert morning.start_ai_build()["started"] == "03:07"
