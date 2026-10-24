"""NSE calendar, session state and publication lag (P-03/P-04), and FII/DII flows."""

from datetime import UTC, date, datetime

import pytest

from tradingagents.dataflows.vendors.nse.calendar import (
    IST,
    Availability,
    NSECalendar,
    SessionState,
    classify_availability,
    parse_holiday_master,
)
from tradingagents.dataflows.vendors.nse.client import Fetched
from tradingagents.dataflows.vendors.nse.flows import get_fii_dii, load_history, parse_flows

HOLIDAYS = {"CM": [
    {"tradingDate": "02-Oct-2026", "description": "Mahatma Gandhi Jayanti"},
    {"tradingDate": "20-Oct-2026", "description": "Dussehra"},
    {"tradingDate": "bad", "description": "ignored"},
]}
CAL = NSECalendar(parse_holiday_master(HOLIDAYS))


def ist(*args):
    return IST.localize(datetime(*args))


@pytest.mark.unit
def test_holidays_and_weekends_are_not_sessions():
    assert not CAL.is_trading_day(date(2026, 10, 20))        # Dussehra (Tue)
    assert not CAL.is_trading_day(date(2026, 10, 18))        # Sunday
    assert CAL.is_trading_day(date(2026, 10, 21))
    assert CAL.previous_session(date(2026, 10, 21)) == date(2026, 10, 19)


@pytest.mark.unit
def test_missing_sessions_finds_the_bar_yahoo_dropped():
    # ^NSEI on Yahoo, Oct 2026: 16, 19, 22 present; 20 is a holiday; 21 is missing.
    have = [date(2026, 10, 16), date(2026, 10, 19), date(2026, 10, 22)]
    assert CAL.missing_sessions(have, date(2026, 10, 16), date(2026, 10, 22)) == [date(2026, 10, 21)]
    assert CAL.unexpected_bars(have + [date(2026, 10, 20)]) == [date(2026, 10, 20)]


@pytest.mark.unit
@pytest.mark.parametrize("moment,state", [
    (ist(2026, 10, 22, 8, 0), SessionState.PRE_MARKET),
    (ist(2026, 10, 22, 9, 5), SessionState.PRE_OPEN),
    (ist(2026, 10, 22, 11, 0), SessionState.OPEN),
    (ist(2026, 10, 22, 16, 0), SessionState.POST_CLOSE),
    (ist(2026, 10, 20, 11, 0), SessionState.NO_SESSION),
])
def test_session_state(moment, state):
    assert CAL.session_state(moment) == state


@pytest.mark.unit
def test_session_state_converts_utc_to_ist():
    utc = datetime(2026, 10, 22, 4, 0, tzinfo=UTC)  # 09:30 IST
    assert CAL.session_state(utc) == SessionState.OPEN


@pytest.mark.unit
def test_yesterdays_figures_during_market_hours_are_pending_not_today():
    a = classify_availability("fii_dii", date(2026, 10, 22), date(2026, 10, 21), ist(2026, 10, 22, 15, 45), CAL)
    assert a.status == Availability.PENDING
    assert "not published yet" in a.message and "21-Oct-2026" in a.message


@pytest.mark.unit
def test_missing_figures_late_in_the_evening_are_late():
    a = classify_availability("fii_dii", date(2026, 10, 22), date(2026, 10, 21), ist(2026, 10, 22, 22, 0), CAL)
    assert a.status == Availability.LATE


@pytest.mark.unit
def test_a_holiday_request_is_answered_by_the_previous_session():
    a = classify_availability("fii_dii", date(2026, 10, 20), date(2026, 10, 19), ist(2026, 10, 20, 21, 0), CAL)
    assert a.status == Availability.FRESH and "not an NSE session" in a.message


PAYLOAD_21 = [
    {"buyValue": "16242.83", "category": "DII", "date": "21-Oct-2026", "netValue": "2891.32", "sellValue": "13351.51"},
    {"buyValue": "13627.54", "category": "FII/FPI", "date": "21-Oct-2026", "netValue": "-3458.7", "sellValue": "17086.24"},
]


class FakeClient:
    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def get_json(self, path, params=None, ttl=None):
        self.calls += 1
        return Fetched(self.payload, "https://www.nseindia.com" + path, datetime.now(IST))


@pytest.mark.unit
def test_parse_flows():
    published, rows = parse_flows(PAYLOAD_21)
    assert published == date(2026, 10, 21)
    assert {r.category: r.net_cr for r in rows} == {"DII": 2891.32, "FII/FPI": -3458.7}


@pytest.mark.unit
def test_flows_during_market_hours_say_todays_are_not_out(tmp_path):
    path = tmp_path / "h.csv"
    report = get_fii_dii(date(2026, 10, 22), client=FakeClient(PAYLOAD_21), calendar=CAL,
                         now=ist(2026, 10, 22, 12, 0), history_path=path)
    assert report.availability.status == Availability.PENDING
    assert report.published == date(2026, 10, 21)
    text = report.to_text()
    assert "pending" in text and "21-Oct-2026" in text and "-3,458.70" in text
    assert date(2026, 10, 21) in load_history(path)           # captured for the future


@pytest.mark.unit
def test_flows_for_a_captured_past_day_come_from_history(tmp_path):
    path = tmp_path / "h.csv"
    get_fii_dii(date(2026, 10, 21), client=FakeClient(PAYLOAD_21), calendar=CAL,
                now=ist(2026, 10, 21, 21, 0), history_path=path)
    client = FakeClient([])
    report = get_fii_dii(date(2026, 10, 21), client=client, calendar=CAL,
                         now=ist(2026, 10, 25, 10, 0), history_path=path)
    assert client.calls == 0
    assert report.availability.status == Availability.FRESH and len(report.rows) == 2


@pytest.mark.unit
def test_flows_for_an_uncaptured_past_day_are_reported_missing(tmp_path):
    payload_22 = [dict(r, date="22-Oct-2026") for r in PAYLOAD_21]
    report = get_fii_dii(date(2026, 10, 16), client=FakeClient(payload_22), calendar=CAL,
                         now=ist(2026, 10, 22, 21, 0), history_path=tmp_path / "h.csv")
    assert report.rows == []
    assert "never captured" in report.availability.message
    assert "Do not estimate" in report.to_text()


class _HolidayClient:
    def __init__(self, payload=None, fail=False):
        self.payload, self.fail = payload, fail

    def get_json(self, path, params=None, ttl=None):
        if self.fail:
            from tradingagents.dataflows.errors import VendorUnavailableError
            raise VendorUnavailableError("nse", "down")
        return Fetched(self.payload, path, None)


@pytest.mark.unit
def test_from_nse_knows_past_special_sessions_and_this_years_muhurat():
    payload = {"CM": [{"tradingDate": "08-Nov-2026", "description": "Diwali Laxmi Pujan*"},
                      {"tradingDate": "10-Nov-2026", "description": "Diwali-Balipratipada"}]}
    cal = NSECalendar.from_nse(_HolidayClient(payload))
    assert cal.is_trading_day(date(2026, 2, 1))              # Sunday Budget session (files verified)
    assert cal.is_trading_day(date(2023, 11, 12))            # Sunday Muhurat 2023
    assert cal.is_trading_day(date(2026, 11, 8))             # NSE's "*": Muhurat session this year
    assert not cal.is_trading_day(date(2026, 11, 10))        # an ordinary holiday
    assert not cal.is_trading_day(date(2026, 1, 31))         # an ordinary Saturday
    # Muhurat day: never "open" in regular hours; after the close its files are expected.
    assert cal.session_state(ist(2026, 11, 8, 10, 0)) == SessionState.PRE_MARKET
    assert cal.session_state(ist(2026, 11, 8, 19, 30)) == SessionState.POST_CLOSE
    # A Budget weekend session trades regular hours.
    assert cal.session_state(ist(2026, 2, 1, 10, 0)) == SessionState.OPEN
    assert cal.previous_session(date(2026, 2, 2)) == date(2026, 2, 1)


@pytest.mark.unit
def test_from_nse_keeps_known_special_sessions_when_nse_is_down():
    cal = NSECalendar.from_nse(_HolidayClient(fail=True))
    assert cal.is_trading_day(date(2025, 2, 1)) and not cal.is_trading_day(date(2025, 2, 2))
