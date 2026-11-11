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

import json
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
SAVED_HOLIDAYS = None    # where the last good holiday list is kept; None: <data cache>/nse/holidays_last_good.json

# Weekend sessions NSE actually held, each verified by downloading its official files (F&O bhavcopy and
# index closes): Budget days, Diwali Muhurat sessions on a weekend, and the 2024 special live sessions.
# NSE's holiday list covers only the current year, so past sessions come from here.
KNOWN_SPECIAL_SESSIONS = frozenset({
    date(2015, 2, 28), date(2016, 10, 30), date(2019, 10, 27), date(2020, 2, 1), date(2020, 11, 14),
    date(2023, 11, 12), date(2024, 1, 20), date(2024, 3, 2), date(2024, 5, 18), date(2025, 2, 1), date(2026, 2, 1),
})

# Muhurat session hours (IST) per year: pre-open, open, close of the equity market. NSE's holiday list gives only
# the date (with a "*"); the hours come in a separate circular each year, so they are entered here by hand.
# 2026-11-08: from press reports of NSE's circular (pre-open 14:05, trading 14:20-15:30); the circular itself not read.
MUHURAT_HOURS: dict[date, tuple[time, time, time]] = {
    date(2026, 11, 8): (time(14, 5), time(14, 20), time(15, 30)),
}

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
                 muhurat_days: set[date] | None = None, source: str = "given"):
        self.source = source     # "nse", "nse (cached copy)", "last saved list", "weekends only" or "given"
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
        source = "nse"
        try:
            fetched = client.get_json("/api/holiday-master", {"type": "trading"}, ttl=86400)
            holidays = parse_holiday_master(fetched.data)
            if getattr(fetched, "stale", False):
                source = "nse (cached copy)"
            why = None if holidays else "NSE's list parsed empty"
        except (VendorError, AttributeError, TypeError, ValueError) as exc:     # unreachable, refused, or a changed format
            holidays, why = {}, str(exc) or type(exc).__name__
        if holidays:
            _save_holidays(holidays)
        else:
            holidays = _load_saved_holidays()
            if holidays:
                logger.warning("NSE holiday list unavailable (%s); using the last saved list", why)
                source = "last saved list"
            else:
                logger.warning("NSE holiday list unavailable (%s) and none saved; using weekends and known special sessions", why)
                return cls(special_sessions=set(KNOWN_SPECIAL_SESSIONS), source="weekends only")
        muhurat = {d for d, name in holidays.items() if name.endswith("*")}
        return cls(holidays, special_sessions=set(KNOWN_SPECIAL_SESSIONS), muhurat_days=muhurat, source=source)

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
            # Closed during regular hours; the Muhurat hour is reported apart, by muhurat_state().
            return SessionState.PRE_MARKET if clock < MARKET_CLOSE else SessionState.POST_CLOSE
        return _state(clock, PRE_OPEN, MARKET_OPEN, MARKET_CLOSE)

    def muhurat_hours(self, day: date) -> tuple[time, time, time] | None:
        """(pre-open, open, close) of ``day``'s Muhurat session, or None: not a Muhurat day, or its hours not entered."""
        return MUHURAT_HOURS.get(day) if day in self.muhurat_days else None

    def muhurat_state(self, now: datetime) -> SessionState | None:
        """The state of the Muhurat session at ``now``, or None when there is no Muhurat session with known hours today.
        Kept apart from session_state, which drives the trade gates and the rule: those follow regular sessions only."""
        local = to_ist(now)
        hours = self.muhurat_hours(local.date())
        return _state(local.time(), *hours) if hours else None


def _state(clock: time, pre_open: time, open_: time, close: time) -> SessionState:
    if clock < pre_open:
        return SessionState.PRE_MARKET
    if clock < open_:
        return SessionState.PRE_OPEN
    if clock < close:
        return SessionState.OPEN
    return SessionState.POST_CLOSE


def _saved_holidays_path():
    from pathlib import Path

    from tradingagents.dataflows.config import get_config

    return Path(SAVED_HOLIDAYS) if SAVED_HOLIDAYS else Path(get_config()["data_cache_dir"]) / "nse" / "holidays_last_good.json"


def _save_holidays(holidays: dict[date, str]) -> None:
    """Keep a good list for the days NSE cannot give one. A failure to save never stops the calendar.

    Through ``replace_file``: each save writes its own uniquely named temp file. A fixed name
    (holidays_last_good.tmp) made two saves at once collide, and on Windows failed with WinError 32 (2026-11-11)."""
    from pathlib import Path

    from tradingagents.dataflows.files import replace_file

    text = json.dumps({"saved_at": now_ist().replace(tzinfo=None).isoformat(timespec="seconds"),
                       "holidays": {d.strftime("%d-%b-%Y"): n for d, n in sorted(holidays.items())}})
    try:
        path = _saved_holidays_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        replace_file(path, lambda tmp: Path(tmp).write_text(text, encoding="utf-8"))
    except OSError as exc:
        logger.warning("could not save the NSE holiday list: %s", exc)


def _load_saved_holidays() -> dict[date, str]:
    try:
        saved = json.loads(_saved_holidays_path().read_text(encoding="utf-8"))
        return {datetime.strptime(d, "%d-%b-%Y").date(): n for d, n in saved["holidays"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


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
