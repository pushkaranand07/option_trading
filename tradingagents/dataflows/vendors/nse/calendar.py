"""NSE trading calendar, session state, and when each dataset is published.

Two real problems live here.

Calendar. NSE holidays change every year (festival dates follow the lunar
calendar), so they cannot be hardcoded. They are read from NSE's own
``/api/holiday-master`` and cached; a weekday that is not a holiday is a
session. The calendar also finds sessions a price series is missing: Yahoo's
``^NSEI`` skipped 21-Oct-2026 although NSE traded and RELIANCE.NS has the bar.

Publication lag. "Why did Nifty fall today?" asked at 15:45 IST finds no
FII/DII figures, no bhavcopy and no delivery data for today: NSE publishes them
in the evening. Rather than letting an agent read yesterday's numbers as
today's, every dated fetch is classified against the date it was asked for:

    fresh     the data is for the requested session
    pending   it is not out yet and is not expected yet (normal; say so)
    late      it should be out by now and is not (vendor delay; say so)
    no_session the requested date was not a trading session

The expected-by times are deliberately conservative approximations. The status
is always decided by the date *inside* the data, never by the clock alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum

import pytz

from tradingagents.dataflows.errors import VendorError

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")
PRE_OPEN = time(9, 0)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# The capital-market segment's list governs equity and index sessions.
HOLIDAY_SEGMENT = "CM"

# Weekend sessions NSE actually held, each verified by downloading its official files (F&O bhavcopy and
# index closes): Budget days, Diwali Muhurat sessions on a weekend, and the 2024 special live sessions.
# NSE's holiday list covers only the current year, so past sessions come from here.
KNOWN_SPECIAL_SESSIONS = frozenset({
    date(2015, 2, 28), date(2016, 10, 30), date(2019, 10, 27), date(2020, 2, 1), date(2020, 11, 14),
    date(2023, 11, 12), date(2024, 1, 20), date(2024, 3, 2), date(2024, 5, 18), date(2025, 2, 1), date(2026, 2, 1),
})

# Sessions NSE held (other files for the day exist; not on NSE's holiday list) whose archive file is gone:
# every URL form returned 404 when re-requested (2026-10-27; 2013-10-09 on 2026-10-28, whose market activity report
# and MTO file exist). They stay sessions; the file kinds listed are
# simply absent. Never fill them from another vendor and label it NSE data (docs/PA_31).
ARCHIVE_HOLE_REASON = "NSE archive hole, unrecoverable"
ARCHIVE_HOLES: dict[date, tuple[str, ...]] = {
    date(2015, 2, 2): ("indices",), date(2015, 3, 12): ("indices",), date(2015, 3, 13): ("indices",),
    date(2015, 5, 19): ("indices",), date(2015, 7, 8): ("indices",), date(2015, 9, 4): ("indices",),
    date(2015, 10, 16): ("indices",), date(2015, 12, 1): ("indices",), date(2016, 6, 20): ("indices",),
    date(2013, 10, 9): ("fo",), date(2021, 3, 30): ("fo",),
}


class SessionState(StrEnum):
    NO_SESSION = "no_session"       # weekend or exchange holiday
    PRE_MARKET = "pre_market"       # before 09:00 IST
    PRE_OPEN = "pre_open"           # 09:00–09:15 call auction
    OPEN = "open"
    POST_CLOSE = "post_close"       # after 15:30; end-of-day files still arriving


class NSECalendar:
    """Sessions of the NSE capital market, from an explicit holiday list."""

    def __init__(self, holidays: dict[date, str] | None = None, special_sessions: set[date] | None = None,
                 muhurat_days: set[date] | None = None):
        self.holidays = dict(holidays or {})
        # Sessions on days that are otherwise closed (e.g. a weekend Muhurat or budget-day session).
        self.special_sessions = set(special_sessions or ())
        # Holidays with a one-hour Muhurat session at a time NSE announces separately: they count as
        # sessions (files are published), but the regular hours never apply.
        self.muhurat_days = set(muhurat_days or ())
        self.special_sessions |= self.muhurat_days

    @classmethod
    def from_nse(cls, client=None) -> NSECalendar:
        """The calendar from NSE's holiday master (cached a day), plus the verified special sessions.

        NSE marks a holiday with a Muhurat session with "*" (e.g. "Diwali Laxmi Pujan*"); those are
        sessions too. Weekends and the known special sessions only, if NSE is unreachable.
        """
        from tradingagents.dataflows.vendors.nse.client import default_client

        client = client or default_client()
        try:
            fetched = client.get_json("/api/holiday-master", {"type": "trading"}, ttl=86400)
        except VendorError as exc:
            logger.warning("NSE holiday list unavailable (%s); using weekends and known special sessions", exc)
            return cls(special_sessions=set(KNOWN_SPECIAL_SESSIONS))
        holidays = parse_holiday_master(fetched.data)
        muhurat = {d for d, name in holidays.items() if name.endswith("*")}
        return cls(holidays, special_sessions=set(KNOWN_SPECIAL_SESSIONS), muhurat_days=muhurat)

    def is_trading_day(self, day: date) -> bool:
        if day in self.special_sessions:
            return True
        return day.weekday() < 5 and day not in self.holidays

    def previous_session(self, day: date) -> date:
        """The last session strictly before ``day``."""
        day -= timedelta(days=1)
        while not self.is_trading_day(day):
            day -= timedelta(days=1)
        return day

    def latest_session(self, day: date) -> date:
        """``day`` if it is a session, otherwise the session before it."""
        return day if self.is_trading_day(day) else self.previous_session(day)

    def sessions_between(self, start: date, end: date) -> list[date]:
        days, day = [], start
        while day <= end:
            if self.is_trading_day(day):
                days.append(day)
            day += timedelta(days=1)
        return days

    def missing_sessions(self, have: list[date] | set[date], start: date, end: date) -> list[date]:
        """Sessions in [start, end] absent from ``have`` — gaps in a vendor's series."""
        have = set(have)
        return [d for d in self.sessions_between(start, end) if d not in have]

    def unexpected_bars(self, have: list[date] | set[date]) -> list[date]:
        """Bars dated on non-sessions (bad vendor rows, or a session the list doesn't know)."""
        return sorted(d for d in set(have) if not self.is_trading_day(d))

    def session_state(self, now: datetime) -> SessionState:
        local = to_ist(now)
        if not self.is_trading_day(local.date()):
            return SessionState.NO_SESSION
        clock = local.time()
        if local.date() in self.muhurat_days:
            # Closed during regular hours; the Muhurat hour itself is not modelled (its time varies).
            return SessionState.PRE_MARKET if clock < MARKET_CLOSE else SessionState.POST_CLOSE
        if clock < PRE_OPEN:
            return SessionState.PRE_MARKET
        if clock < MARKET_OPEN:
            return SessionState.PRE_OPEN
        if clock < MARKET_CLOSE:
            return SessionState.OPEN
        return SessionState.POST_CLOSE


def parse_holiday_master(payload: dict) -> dict[date, str]:
    holidays = {}
    for row in payload.get(HOLIDAY_SEGMENT, []):
        try:
            day = datetime.strptime(row["tradingDate"], "%d-%b-%Y").date()
        except (KeyError, ValueError):
            continue
        holidays[day] = row.get("description", "").strip()
    return holidays


def to_ist(moment: datetime) -> datetime:
    """``moment`` in IST; a naive datetime is taken to already be IST."""
    if moment.tzinfo is None:
        return IST.localize(moment)
    return moment.astimezone(IST)


def now_ist() -> datetime:
    return datetime.now(IST)


# ------------------------------------------------------------- publication lag

# When each end-of-day dataset can be relied on, IST, on the session's own day.
# Conservative: NSE often publishes earlier, and the status is decided by the
# data's own date, so an early file is simply "fresh".
EXPECTED_BY = {
    "fii_dii": time(20, 0),          # provisional FII/DII cash figures
    "cm_bhavcopy": time(19, 0),      # equity bhavcopy
    "delivery": time(19, 0),         # sec_bhavdata_full (delivery quantity / %)
    "fo_bhavcopy": time(19, 0),      # F&O bhavcopy (OI, settle prices, lot sizes)
}


class Availability(StrEnum):
    FRESH = "fresh"
    PENDING = "pending"
    LATE = "late"
    NO_SESSION = "no_session"


@dataclass(frozen=True)
class DataAvailability:
    dataset: str
    requested: date
    published: date | None        # the session the data we hold is actually for
    status: Availability
    message: str

    @property
    def usable_for_requested_date(self) -> bool:
        return self.status == Availability.FRESH


def classify_availability(
    dataset: str,
    requested: date,
    published: date | None,
    now: datetime,
    calendar: NSECalendar,
) -> DataAvailability:
    """Say whether ``published`` data answers a request for ``requested``, and if not, why."""
    if not calendar.is_trading_day(requested):
        session = calendar.previous_session(requested)
        status = Availability.FRESH if published == session else Availability.NO_SESSION
        return DataAvailability(
            dataset, requested, published, status,
            f"{requested:%d-%b-%Y} was not an NSE session; the latest session is {session:%d-%b-%Y}"
            + ("" if published == session else f"; held data is for {_fmt(published)}"),
        )
    if published == requested:
        return DataAvailability(dataset, requested, published, Availability.FRESH,
                                f"{dataset} for {requested:%d-%b-%Y} is published")
    local = to_ist(now)
    expected = IST.localize(datetime.combine(requested, EXPECTED_BY.get(dataset, time(20, 0))))
    if local < expected:
        return DataAvailability(
            dataset, requested, published, Availability.PENDING,
            f"{dataset} for {requested:%d-%b-%Y} is not published yet (NSE publishes it in the "
            f"evening, normally by ~{expected:%H:%M} IST). Latest available is for {_fmt(published)}; "
            "do not read it as today's figure.",
        )
    return DataAvailability(
        dataset, requested, published, Availability.LATE,
        f"{dataset} for {requested:%d-%b-%Y} should be out by ~{expected:%H:%M} IST but is not; "
        f"latest available is for {_fmt(published)}. Treat today's value as missing.",
    )


def _fmt(day: date | None) -> str:
    return f"{day:%d-%b-%Y}" if day else "no date"
