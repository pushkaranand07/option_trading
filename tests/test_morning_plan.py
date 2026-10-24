"""Morning plan: session times, holidays and Muhurat, saving, and keeping the AI view on a data refresh."""

from datetime import date

import pytest

from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import morning

CAL = NSECalendar({date(2026, 11, 10): "Diwali-Balipratipada", date(2026, 11, 8): "Diwali Laxmi Pujan*"},
                  muhurat_days={date(2026, 11, 8)})


@pytest.mark.unit
def test_session_times_holidays_and_the_index_derivatives_close_from_december():
    s = morning.session(date(2026, 11, 9), CAL)
    assert s["trading"] and (s["open"], s["first_signal"], s["close"]) == ("09:15", "09:45", "15:30")
    assert s["index_derivatives_close"] == "15:30" and s["next_session"] == "2026-11-11"     # 10th is a holiday
    hol = morning.session(date(2026, 11, 10), CAL)
    assert not hol["trading"] and hol["holiday"] == "Diwali-Balipratipada"
    muhurat = morning.session(date(2026, 11, 8), CAL)
    assert muhurat["muhurat"] and not muhurat["trading"]                 # no regular session to plan for
    assert morning.session(date(2026, 12, 7), CAL)["index_derivatives_close"] == "15:45"   # SEBI CAS circular


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.setattr(morning, "PLAN_DIR", tmp_path)
    monkeypatch.setattr(morning, "context", lambda symbol, day: {"symbol": symbol})
    calls = []

    def ai_view(ticker, day):
        calls.append(ticker)
        return {"rating": "Hold", "decision": "wait", "minutes": 1.0}

    monkeypatch.setattr(morning, "ai_view", ai_view)
    return calls


@pytest.mark.unit
def test_build_saves_the_plan_and_runs_the_ai_on_trading_days_only(fake):
    plan = morning.build(date(2026, 11, 9), with_ai=True, calendar=CAL)
    assert fake == ["^NSEI", "^NSEBANK"] and plan["indices"]["NIFTY"]["ai"]["rating"] == "Hold"
    assert morning.load(date(2026, 11, 9))["session"]["date"] == "2026-11-09"
    morning.build(date(2026, 11, 10), with_ai=True, calendar=CAL)       # a holiday: no AI calls
    assert fake == ["^NSEI", "^NSEBANK"]


@pytest.mark.unit
def test_a_data_refresh_keeps_the_mornings_ai_view(fake):
    morning.build(date(2026, 11, 9), with_ai=True, calendar=CAL)
    again = morning.build(date(2026, 11, 9), with_ai=False, calendar=CAL)
    assert again["indices"]["BANKNIFTY"]["ai"]["rating"] == "Hold" and len(fake) == 2


@pytest.mark.unit
def test_an_ai_failure_is_recorded_not_raised(fake, monkeypatch):
    def broken(ticker, day):
        raise RuntimeError("Azure said no")
    monkeypatch.setattr(morning, "ai_view", broken)
    plan = morning.build(date(2026, 11, 9), with_ai=True, calendar=CAL)
    assert "Azure said no" in plan["indices"]["NIFTY"]["ai"]["error"]
