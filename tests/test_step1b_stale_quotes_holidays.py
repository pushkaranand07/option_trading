"""Audit step 1b. (1) Take refuses a chain whose quotes are stale: NSE's chain timestamp older than 60 s, from another
IST date, missing, or ahead of this clock. (2) The NSE holiday list survives NSE failures: the last good list is
kept on disk and used; only with none saved is it weekends-only, and the page says so."""

from datetime import date

import pytest

from tests.test_take_honest_entry import at, chain, take, world  # noqa: F401  (world is a fixture)
from tradingagents.dataflows.errors import VendorError, VendorUnavailableError
from tradingagents.dataflows.vendors.nse import calendar as nse_cal
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from tradingagents.dataflows.vendors.nse.client import Fetched
from webapp import server, signals

APP = (__import__("pathlib").Path(server.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")


def stamped(ts, **kw):
    return chain(**kw) | {"timestamp": ts}


# ---------------------------------------------------------------- (1) stale quotes

@pytest.mark.unit
def test_quotes_119_s_old_are_taken_121_s_old_are_refused(world):
    world["live"]["chain"] = stamped("12-Nov-2026 09:58:01")                      # the clock reads 10:00:00
    assert take(world).status_code == 200
    world["live"]["chain"] = stamped("12-Nov-2026 09:57:59")
    r = take(world, candidate=1)
    assert r.status_code == 400 and "121 s old" in r.json()["detail"]


@pytest.mark.unit
def test_quotes_from_another_day_are_refused(world):
    world["live"]["chain"] = stamped("04-Nov-2026 10:00:00")                      # yesterday at the same time
    r = take(world)
    assert r.status_code == 400 and "from 04-Nov-2026" in r.json()["detail"]


@pytest.mark.unit
def test_a_chain_without_a_timestamp_is_refused(world):
    world["live"]["chain"] = stamped(None)
    r = take(world)
    assert r.status_code == 400 and "no timestamp" in r.json()["detail"]


@pytest.mark.unit
def test_quotes_ahead_of_this_clock_are_refused(world):
    world["live"]["chain"] = stamped("12-Nov-2026 10:02:00")                      # two minutes in the future
    r = take(world)
    assert r.status_code == 400 and "clock" in r.json()["detail"]


# ---------------------------------------------------------------- (2) holiday list fallback

PAYLOAD = {"CM": [{"tradingDate": "10-Nov-2026", "description": "Diwali-Balipratipada"}]}
HOLIDAY = date(2026, 11, 10)


class Client:
    def __init__(self, payload=None, error=None):
        self.payload, self.error = payload, error

    def get_json(self, path, params=None, ttl=None):
        if self.error:
            raise self.error
        return Fetched(self.payload, path, None)


@pytest.fixture
def saved(tmp_path, monkeypatch):
    path = tmp_path / "holidays_last_good.json"
    monkeypatch.setattr(nse_cal, "SAVED_HOLIDAYS", path, raising=False)
    return path


@pytest.mark.unit
@pytest.mark.parametrize("error", [VendorUnavailableError("nse", "down"), VendorError("NSE answered 403")])
def test_a_failed_fetch_uses_the_last_good_list_saved_on_disk(saved, error):
    good = NSECalendar.from_nse(Client(PAYLOAD))
    assert not good.is_trading_day(HOLIDAY) and saved.exists()
    cal = NSECalendar.from_nse(Client(error=error))
    assert not cal.is_trading_day(HOLIDAY), "the saved list was not used"
    assert getattr(cal, "source", None) == "last saved list"


@pytest.mark.unit
def test_an_empty_or_changed_list_does_not_replace_the_saved_one(saved):
    NSECalendar.from_nse(Client(PAYLOAD))
    cal = NSECalendar.from_nse(Client({"CM": []}))                                 # NSE answered, but nothing parsed
    assert not cal.is_trading_day(HOLIDAY) and getattr(cal, "source", None) == "last saved list"
    assert "10-Nov-2026" in saved.read_text(encoding="utf-8")


@pytest.mark.unit
def test_with_nothing_saved_it_is_weekends_only_and_the_page_says_so(saved, monkeypatch):
    cal = NSECalendar.from_nse(Client(error=VendorError("NSE answered 403")))
    assert cal.is_trading_day(HOLIDAY) and getattr(cal, "source", None) == "weekends only"
    monkeypatch.setattr(signals, "nse_calendar", lambda: cal)
    warning = server.status().get("calendar_warning")
    assert warning and "holiday" in warning.lower()
    loader = APP[APP.index("async function loadStatus"):]
    assert "bannerTexts(S.status)" in loader[:900] and "st?.calendar_warning" in APP[APP.index("const bannerTexts"):][:200]


@pytest.mark.unit
def test_a_good_fetch_says_nse_and_shows_no_warning(saved, monkeypatch):
    cal = NSECalendar.from_nse(Client(PAYLOAD))
    assert getattr(cal, "source", None) == "nse"
    monkeypatch.setattr(signals, "nse_calendar", lambda: cal)
    assert "calendar_warning" in server.status() and server.status()["calendar_warning"] is None
