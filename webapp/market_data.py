"""Market data: DhanHQ v2 when DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN are set, Yahoo Finance otherwise.

Yahoo is delayed and has no Indian option chains, so the option chain needs Dhan.
Dhan's limits (quotes 1/s, one unique option-chain request per 3 s) are kept by
caching every response for at least that long.
"""

from __future__ import annotations

import contextlib
import csv
import json
import logging
import math
import os
import threading
import time as _time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from webapp import dhan_guard, latency, timeutil

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")
DHAN_BASE = "https://api.dhan.co/v2"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
CACHE_DIR = Path(os.getenv("TRADINGAGENTS_CACHE_DIR") or Path.home() / ".tradingagents" / "cache")

# symbol: (display name, Dhan security id, Dhan segment, Yahoo symbol, option lot size, strike step)
# The lot sizes here are only a fallback: exchanges revise them (NIFTY 75 -> 65 in Jan-2026), so the live lot
# comes from Dhan's scrip master (``index_lots``). Fallback values as listed there on 2026-10-24.
INDICES = {
    "NIFTY": ("NIFTY 50", 13, "IDX_I", "^NSEI", 65, 50),
    "BANKNIFTY": ("NIFTY BANK", 25, "IDX_I", "^NSEBANK", 30, 100),
    "FINNIFTY": ("FIN NIFTY", 27, "IDX_I", "NIFTY_FIN_SERVICE.NS", 60, 50),
    "MIDCPNIFTY": ("MIDCAP SELECT", 442, "IDX_I", "NIFTY_MID_SELECT.NS", 120, 25),
    "SENSEX": ("SENSEX", 51, "IDX_I", "^BSESN", 20, 100),
}

# Offered by search when the Dhan scrip master is not loaded.
NIFTY50 = ["ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL", "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY", "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO", "PNB"]


class DataError(Exception):
    pass


class _TTLCache:
    """Each value is kept ``ttl`` seconds from the moment its fetch started, so its age never exceeds ``ttl``.

    One fetch per key at a time: callers that miss together wait for that fetch instead of repeating it,
    and a result never replaces one whose fetch started later. While the market is open, ``refresh_ahead``
    refetches the keys read in the last ``HOT_SECONDS`` shortly before they expire, so a request reads
    memory instead of waiting on Yahoo / NSE / Dhan.
    """

    HOT_SECONDS = 90
    LEAD = 1.0          # refetch this long before expiry, or twice the key's last fetch time (at most 40% of the ttl)
    BACKOFF = 30.0      # a key whose refetch failed is left to the requests for this long
    WORKERS = 4         # refetches at once, so one slow source does not hold up the rest

    def __init__(self):
        self._d: dict = {}              # key -> (monotonic time the fetch started, value)
        self._uses: dict = {}           # key -> (fn, ttl, last read)
        self._failed: dict = {}         # key -> monotonic time of the last failed refetch
        self._took: dict = {}           # key -> seconds its last fetch took
        self._key_locks: dict = {}
        self._lock = threading.Lock()

    def get(self, key, ttl: float, fn):
        now = _time.monotonic()
        with self._lock:
            self._uses[key] = (fn, ttl, now)
            hit = self._d.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        with key_lock:
            with self._lock:
                hit = self._d.get(key)
                if hit and _time.monotonic() - hit[0] < ttl:     # another caller fetched it meanwhile
                    return hit[1]
            return self._fetch(key, fn)

    def peek(self, key, ttl: float):
        """The value if one younger than ``ttl`` is held, else None; never fetches and never marks the key as read
        (so it does not keep the key hot for ``refresh_ahead``)."""
        with self._lock:
            hit = self._d.get(key)
            return hit[1] if hit and _time.monotonic() - hit[0] < ttl else None

    def _fetch(self, key, fn):
        started = _time.monotonic()
        value = fn()
        took = _time.monotonic() - started
        latency.observe(f"fetch {key[0] if isinstance(key, tuple) else key}", took)
        with self._lock:
            self._took[key] = took
            old = self._d.get(key)
            if old is None or old[0] <= started:
                self._d[key] = (started, value)
            else:
                value = old[1]
        return value

    def refresh_ahead(self) -> int:
        """Refetch the hot keys about to expire, up to ``WORKERS`` at once; returns how many were refetched."""
        now = _time.monotonic()
        with self._lock:
            due = [(k, fn) for k, (fn, ttl, read) in self._uses.items()
                   if now - read < self.HOT_SECONDS and k in self._d
                   and now - self._d[k][0] >= ttl - min(max(self.LEAD, 2 * self._took.get(k, 0)), ttl * 0.4)
                   and now - self._failed.get(k, -1e9) >= self.BACKOFF]
        if not due:
            return 0
        with ThreadPoolExecutor(min(self.WORKERS, len(due))) as pool:
            return sum(pool.map(lambda kf: self._refresh(*kf), due))

    def _refresh(self, key, fn) -> bool:
        with self._lock:
            key_lock = self._key_locks.setdefault(key, threading.Lock())
        if not key_lock.acquire(blocking=False):                # a request is fetching it right now
            return False
        try:
            self._fetch(key, fn)
            return True
        except Exception as exc:
            self._failed[key] = _time.monotonic()
            logger.warning("Refresh of %s failed: %s", key, exc)
            return False
        finally:
            key_lock.release()


_cache = _TTLCache()
_refresher: threading.Thread | None = None


def start_refresh_ahead(tick: float = 0.25) -> None:
    """Keep the data in use fresh in the background while the market is open (the server calls this once)."""
    global _refresher
    if _refresher is not None:
        return

    def run():
        from webapp import signals

        index_lots()                                         # parse the scrip master before the first request
        open_checked, is_open = -1e9, False
        while True:
            if _time.monotonic() - open_checked > 30:
                try:
                    is_open = signals.market_open()
                except Exception:
                    is_open = False
                open_checked = _time.monotonic()
            if is_open:
                _cache.refresh_ahead()
            _time.sleep(tick)

    _refresher = threading.Thread(target=run, name="refresh-ahead", daemon=True)
    _refresher.start()


# ---------- Dhan ----------

class Dhan:
    def __init__(self):
        self.client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
        self.token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
        self._quote_lock = threading.Lock()
        self._last_quote = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.token)

    def post(self, path: str, body: dict) -> dict:
        # Only market-data paths pass the guard; an account path raises DhanAccountAccessBlocked before sending.
        r = dhan_guard.request("POST", f"{DHAN_BASE}{path}", json=body, timeout=15, token=self.token, client_id=self.client_id)
        try:
            data = r.json()
        except ValueError:
            raise DataError(f"Dhan {path}: HTTP {r.status_code}") from None
        if r.status_code != 200 or data.get("status") == "failure" or data.get("errorCode"):
            msg = data.get("errorMessage") or (data.get("remarks") or {}).get("error_message") or data
            code = data.get("errorCode") or (data.get("remarks") or {}).get("error_code") or r.status_code
            if str(code) in ("DH-902", "806"):
                msg = "Your Dhan account has no Data API subscription (Dhan web > DhanHQ Trading APIs > Data APIs)."
            elif str(code) in ("DH-901", "807", "808", "809", "810"):
                msg = "Dhan rejected the access token. It expires every 24 hours; generate a new one."
            raise DataError(f"Dhan: {msg}")
        return data

    def quote(self, body: dict) -> dict:
        # Quote APIs allow one request per second.
        with self._quote_lock:
            wait = 1.05 - (_time.monotonic() - self._last_quote)
            if wait > 0:
                _time.sleep(wait)
            try:
                return self.post("/marketfeed/ohlc", body).get("data", {})
            finally:
                self._last_quote = _time.monotonic()


dhan = Dhan()


def _scrip_master_path() -> Path:
    """Dhan's public instrument list (no login needed), downloaded at most once a day."""
    path = CACHE_DIR / "dhan-scrip-master.csv"
    if (not path.exists()
            or datetime.fromtimestamp(path.stat().st_mtime, timeutil.IST).date() != timeutil.today_ist()):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        r = dhan_guard.request("GET", SCRIP_MASTER_URL, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def load_index_lots(path: Path) -> dict[str, int]:
    """Current option lot size per index (NSE and BSE index options) from a scrip-master file."""
    lots: dict[str, dict[int, int]] = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if row.get("SEM_INSTRUMENT_NAME") != "OPTIDX":
                continue
            under = (row.get("SEM_TRADING_SYMBOL") or "").split("-")[0].strip().upper()
            try:
                lot = int(float(row.get("SEM_LOT_UNITS") or 0))
            except ValueError:
                continue
            if under and lot > 0:
                counts = lots.setdefault(under, {})
                counts[lot] = counts.get(lot, 0) + 1
    # During a lot revision old and new contracts coexist; the most common lot is the current one.
    return {u: max(c, key=c.get) for u, c in lots.items()}


def _parsed_scrip_master(name: str, parse):
    """``parse(path)`` of today's scrip master. Parsing its ~216k rows takes seconds, so the result is kept
    beside the file and parsed again only when a new file is downloaded."""
    path = _scrip_master_path()
    side, stamp = path.with_name(f"{path.stem}.{name}.json"), path.stat().st_mtime
    try:
        saved = json.loads(side.read_text(encoding="utf-8"))
        if saved["stamp"] == stamp:
            return saved["data"]
    except (OSError, ValueError, KeyError):
        pass
    data = parse(path)
    with contextlib.suppress(OSError):
        side.write_text(json.dumps({"stamp": stamp, "data": data}), encoding="utf-8")
    return data


def index_lots() -> dict[str, int]:
    """Live index lot sizes, refreshed daily; {} when the scrip master cannot be fetched (then INDICES applies)."""
    try:
        return _cache.get("index_lots", 3600, lambda: _parsed_scrip_master("lots", load_index_lots))
    except Exception:
        return {}


def _load_scrip_master() -> dict[str, tuple[int, str]]:
    """NSE cash-market equities: trading symbol -> (security id, company name). Refreshed daily."""
    path = _scrip_master_path()
    out = {}
    with path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        id_col = next(c for c in reader.fieldnames if "SECURITY_ID" in c)
        for row in reader:
            if (row.get("SEM_EXM_EXCH_ID") == "NSE" and row.get("SEM_SEGMENT") == "E"
                    and row.get("SEM_SERIES") == "EQ"):
                sym = row["SEM_TRADING_SYMBOL"].strip().upper()
                name = (row.get("SM_SYMBOL_NAME") or row.get("SEM_CUSTOM_SYMBOL") or sym).strip()
                out[sym] = (int(float(row[id_col])), name.title())
    return out


_equities: dict[str, tuple[int, str]] = {}


def equities() -> dict[str, tuple[int, str]]:
    global _equities
    if not _equities and dhan.enabled:
        try:
            _equities = {s: tuple(v) for s, v in _cache.get(
                "scrip", 3600, lambda: _parsed_scrip_master("equities", lambda _: _load_scrip_master())).items()}
        except Exception:
            _equities = {}
    return _equities


# ---------- instruments ----------

def instrument(symbol: str) -> dict:
    s = symbol.strip().upper()
    if s in INDICES:
        name, sid, seg, yahoo, lot, step = INDICES[s]
        return {"symbol": s, "name": name, "kind": "INDEX", "id": sid, "segment": seg, "yahoo": yahoo,
                "lot": index_lots().get(s, lot), "step": step, "has_options": True}
    eq = equities().get(s)
    return {"symbol": s, "name": eq[1] if eq else s, "kind": "EQUITY", "id": eq[0] if eq else None,
            "segment": "NSE_EQ", "yahoo": f"{s}.NS", "lot": None, "step": None, "has_options": False}


def search(q: str, limit: int = 12) -> list[dict]:
    q = q.strip().upper()
    if not q:
        return []
    hits = [{"symbol": k, "name": v[0], "kind": "INDEX"} for k, v in INDICES.items() if q in k or q in v[0]]
    pool = equities() or {s: (None, s) for s in NIFTY50}
    starts = [k for k in pool if k.startswith(q)]
    contains = [k for k, v in pool.items() if k not in starts and (q in k or q in v[1].upper())]
    for k in sorted(starts, key=len) + contains:
        hits.append({"symbol": k, "name": pool[k][1], "kind": "EQUITY"})
        if len(hits) >= limit:
            break
    if not hits and q.isalnum():
        hits.append({"symbol": q, "name": q, "kind": "EQUITY"})
    return hits


# ---------- quotes ----------

def quotes(symbols: list[str]) -> dict[str, dict]:
    insts = [instrument(s) for s in dict.fromkeys(symbols) if s]
    key = ("q", tuple(i["symbol"] for i in insts))
    return _cache.get(key, 1.5 if dhan.enabled else 15, lambda: _quotes(insts))


def _quotes(insts: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    session = _warm_prev_closes(insts)
    dhan_insts = [i for i in insts if i["id"] is not None] if dhan.enabled else []
    if dhan_insts:
        body: dict[str, list[int]] = {}
        for i in dhan_insts:
            body.setdefault(i["segment"], []).append(i["id"])
        try:
            data = dhan.quote(body)
            for i in dhan_insts:
                row = (data.get(i["segment"]) or {}).get(str(i["id"]))
                if row and row.get("last_price"):
                    ltp, prev = float(row["last_price"]), float((row.get("ohlc") or {}).get("close") or 0)
                    out[i["symbol"]] = _quote_row(i, ltp, prev, row.get("ohlc") or {}, "dhan",
                                                  checked=_checked_prev(i, prev, "dhan", session))
        except DataError:
            pass
    for i in insts:
        if i["symbol"] not in out:
            q = _cache.get(("yq", i["yahoo"]), 15, lambda i=i: _yahoo_quote(i, session))
            if q:
                out[i["symbol"]] = q
    return out


def _quote_row(inst, ltp, prev, ohlc, source, checked: tuple[float | None, str, str | None] | None = None):
    """``checked``: (previous close, its source, warning) from ``prev_close``; it replaces the vendor's ``prev``."""
    prev_source, warning = source, None
    if checked is not None and _valid_close(checked[0]):
        prev, prev_source, warning = checked
    if not _valid_close(prev):                                # NaN / inf / 0 / negative: never emitted
        prev, prev_source = None, "none"
        warning = "No valid previous close from any source; change not shown."
    chg = ltp - prev if prev else 0.0
    row = {"symbol": inst["symbol"], "name": inst["name"], "ltp": round(ltp, 2),
           "prev_close": round(prev, 2) if prev else None,
           "change": round(chg, 2), "change_pct": round(chg / prev * 100, 2) if prev else 0.0,
           "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"), "source": source,
           "prev_close_source": prev_source}
    if warning:
        row["prev_close_warning"] = warning
    return row


def _yahoo_quote(inst, session: date | None = None) -> dict | None:
    try:
        fi = yf.Ticker(inst["yahoo"]).fast_info
        ltp, prev = float(fi["last_price"]), float(fi["previous_close"])
        ohlc = {"open": round(float(fi["open"]), 2), "high": round(float(fi["day_high"]), 2),
                "low": round(float(fi["day_low"]), 2)}
        return _quote_row(inst, ltp, prev, ohlc, "yahoo", checked=_checked_prev(inst, prev, "yahoo", session))
    except Exception:
        return None


# ---------- previous close (audit M1) ----------

PREV_CLOSE_TOLERANCE = 0.005     # sources further apart than 0.5% are reported in the quote row


def _valid_close(v) -> bool:
    """A usable close: a finite number above zero (NaN, inf, 0 and negatives count as missing)."""
    try:
        return math.isfinite(float(v)) and float(v) > 0
    except (TypeError, ValueError):
        return False


def quote_session_date(now: datetime | None = None, calendar=None) -> date:
    """The session the live price belongs to: today once today's session (or its Muhurat hour) has reached its
    pre-open, else the last session before today. Before Monday's open the price is still Friday's (or a weekend
    Muhurat session's)."""
    from tradingagents.dataflows.vendors.nse.calendar import SessionState
    from webapp import signals

    cal = calendar or signals.nse_calendar()
    now = (now or timeutil.now_ist()).astimezone(timeutil.IST)
    today = now.date()
    if cal.is_trading_day(today):
        state = cal.muhurat_state(now) or cal.session_state(now)
        if state not in (SessionState.PRE_MARKET, SessionState.NO_SESSION):
            return today
    return cal.previous_session(today)


def _close_before(df: pd.DataFrame | None, session: date, expected: date) -> float | None:
    """The last daily close strictly before ``session``, if the bars hold the expected previous session."""
    if df is None or df.empty:
        return None
    days = pd.Index([ts.date() for ts in df.index])
    before = df[days < session]
    if before.empty or before.index[-1].date() < expected:     # the bars miss that session (a vendor gap)
        return None
    close = float(before["close"].iloc[-1])
    return close if _valid_close(close) else None


def _reference_close(inst: dict, session: date, expected: date) -> tuple[float, str] | None:
    """(close, source) of the previous session from the app's own daily bars, else Dhan's daily history."""
    src = None
    try:
        # A chart's fresh 1D bars if held; else fetched here, under the caller's 600 s "prev" key. Not through
        # candles(): that would keep its 20 s key hot and refresh_ahead would re-download it every ~20 s.
        df, src = _cache.peek(("c", inst["symbol"], "1D"), 20) or _candles(inst, "1D")    # 20 s: candles' 1D ttl
        value = _close_before(df, session, expected)
        if value is not None:
            return value, f"bars ({src})"
    except DataError:
        pass
    if dhan.enabled and inst["id"] is not None and src != "dhan":
        try:
            value = _close_before(_dhan_bars(inst, "1D"), session, expected)
            if value is not None:
                return value, "dhan daily"
        except DataError:
            pass
    return None


def prev_close(inst: dict, ltp_session_date: date, *, vendor: float | None = None, vendor_source: str = "vendor",
               calendar=None) -> tuple[float | None, str, str | None]:
    """(previous close, its source, warning or None) for a price from ``ltp_session_date``.

    The previous close is the close of the last completed session strictly before the quote's session (NSE
    calendar: weekends, holidays and Muhurat sessions), from the app's own daily bars; without them from Dhan's
    daily history (Dhan enabled only); then the vendor's own value. When two available sources differ by more than
    ``PREV_CLOSE_TOLERANCE`` the warning names both."""
    from webapp import signals

    cal = calendar or signals.nse_calendar()
    expected = cal.previous_session(ltp_session_date)
    found = _cached_reference(inst, ltp_session_date, expected)
    sources = [found] if found else []
    if _valid_close(vendor):
        sources.append((float(vendor), vendor_source))
    if not sources:
        return None, "none", None
    value, source = sources[0]
    warning = None
    for other, other_source in sources[1:]:
        gap = abs(other - value) / value
        if gap > PREV_CLOSE_TOLERANCE:
            warning = (f"Previous close differs between sources: {source} {value:,.2f} vs {other_source} "
                       f"{other:,.2f} ({gap:.1%}); using {source} (close of {expected:%d-%b}).")
    return value, source, warning


def _cached_reference(inst: dict, session: date, expected: date) -> tuple[float, str] | None:
    """``_reference_close`` cached per symbol and session."""
    return _cache.get(("prev", inst["symbol"], session.isoformat()), 600,
                      lambda: _reference_close(inst, session, expected))


PREV_WORKERS = 8      # daily-bars downloads at once when a cold quote request needs several previous closes


def _warm_prev_closes(insts: list[dict]) -> date | None:
    """Fetch the previous closes of ``insts`` in parallel before the quote rows are built (a cold request with N
    symbols then costs about one daily-bars download, not N). Returns the quote session, or None if unknown."""
    from webapp import signals

    try:
        session = quote_session_date()
        expected = signals.nse_calendar().previous_session(session)
    except Exception as exc:
        logger.warning("quote session unknown: %s", exc)
        return None

    def one(inst):
        try:
            _cached_reference(inst, session, expected)
        except Exception as exc:                              # the row falls back to the vendor's value
            logger.warning("previous close lookup for %s failed: %s", inst["symbol"], exc)

    if len(insts) > 1:
        with ThreadPoolExecutor(min(PREV_WORKERS, len(insts))) as pool:
            list(pool.map(one, insts))
    return session


def _checked_prev(inst: dict, vendor: float, vendor_source: str,
                  session: date | None = None) -> tuple[float | None, str, str | None]:
    """``prev_close`` for a quote now; the vendor's value alone if the calendar or the bars fail outright."""
    try:
        return prev_close(inst, session or quote_session_date(), vendor=vendor, vendor_source=vendor_source)
    except Exception as exc:                                  # a quote is never lost over its previous close
        logger.warning("previous close check for %s failed: %s", inst["symbol"], exc)
        return vendor, vendor_source, None


# ---------- candles ----------

# timeframe: (Dhan interval or None for daily, days of history, Yahoo period, Yahoo interval)
TIMEFRAMES = {
    "1m": ("1", 4, "5d", "1m"),
    "5m": ("5", 59, "60d", "5m"),   # ~60 sessions: also the backtest window
    "15m": ("15", 59, "60d", "15m"),
    "1h": ("60", 89, "3mo", "60m"),
    "1D": (None, 730, "2y", "1d"),
}

# While the market is open, a last bar that started longer ago than this means the feed has stopped:
# two bars (Yahoo's bars arrive a few minutes late, so one bar is not enough).
MAX_BAR_AGE = {"1m": 180, "5m": 600, "15m": 1800, "1h": 7200}


def bar_age(df: pd.DataFrame, now: datetime | None = None) -> float | None:
    """Seconds since the last bar started, or None without bars."""
    if df is None or df.empty:
        return None
    return ((now or datetime.now(IST)) - df.index[-1].to_pydatetime()).total_seconds()


def stale_bars(df: pd.DataFrame, tf: str, market_open: bool, now: datetime | None = None) -> float | None:
    """The last bar's age in seconds when it is too old to trade on (market open only), else None."""
    age = bar_age(df, now)
    if not market_open or tf not in MAX_BAR_AGE:
        return None
    return age if age is not None and age > MAX_BAR_AGE[tf] else None


def candles(symbol: str, tf: str = "5m") -> tuple[pd.DataFrame, str]:
    inst = instrument(symbol)
    if tf not in TIMEFRAMES:
        raise DataError(f"Unknown timeframe {tf}")
    ttl = 4 if tf != "1D" else 20
    return _cache.get(("c", inst["symbol"], tf), ttl, lambda: _candles(inst, tf))


def _dhan_bars(inst: dict, tf: str) -> pd.DataFrame | None:
    """Dhan's bars for ``tf`` (intraday or daily history), or None when Dhan returns none; raises DataError."""
    interval, days, _, _ = TIMEFRAMES[tf]
    now = datetime.now(IST)
    body = {"securityId": str(inst["id"]), "exchangeSegment": inst["segment"],
            "instrument": inst["kind"], "oi": False}
    if interval:
        body |= {"interval": interval,
                 "fromDate": (now - timedelta(days=days)).strftime("%Y-%m-%d 09:00:00"),
                 "toDate": (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")}
        data = dhan.post("/charts/intraday", body)
    else:
        body |= {"expiryCode": 0, "fromDate": (now - timedelta(days=days)).strftime("%Y-%m-%d"),
                 "toDate": (now + timedelta(days=1)).strftime("%Y-%m-%d")}
        data = dhan.post("/charts/historical", body)
    if not data.get("timestamp"):
        return None
    df = pd.DataFrame({k: data[k] for k in ("open", "high", "low", "close", "volume")},
                      index=pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert(IST))
    return df.astype(float)


def _candles(inst: dict, tf: str) -> tuple[pd.DataFrame, str]:
    _, _, y_period, y_interval = TIMEFRAMES[tf]
    if dhan.enabled and inst["id"] is not None:
        try:
            df = _dhan_bars(inst, tf)
            if df is not None:
                return df, "dhan"
        except DataError:
            pass
    try:
        df = yf.Ticker(inst["yahoo"]).history(period=y_period, interval=y_interval, auto_adjust=False)
    except Exception:                                  # no internet / DNS, Yahoo throttling
        df = pd.DataFrame()
    if df.empty:
        saved = _last_good(inst["symbol"], tf)
        if saved is None:
            raise DataError(f"No price data for {inst['symbol']} (Yahoo unreachable and nothing saved yet)")
        return saved
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    df.index = df.index.tz_convert(IST) if df.index.tz else df.index.tz_localize(IST)
    df = df.astype(float)
    _remember(inst["symbol"], tf, df)
    return df, "yahoo"


# Last good candles per symbol and timeframe, in memory and on disk, so a dropped connection or a Yahoo hiccup
# shows the latest saved prices (labelled as such) instead of an error.
LAST_GOOD_DIR = CACHE_DIR / "webapp_candles"
_good: dict[tuple[str, str], pd.DataFrame] = {}
_good_saved: dict[tuple[str, str], float] = {}


def _remember(symbol: str, tf: str, df: pd.DataFrame) -> None:
    key = (symbol, tf)
    _good[key] = df
    if _time.monotonic() - _good_saved.get(key, -1e9) < 60:          # disk at most once a minute per chart
        return
    _good_saved[key] = _time.monotonic()
    try:
        LAST_GOOD_DIR.mkdir(parents=True, exist_ok=True)
        df.to_pickle(LAST_GOOD_DIR / f"{symbol}_{tf}.pkl")
    except OSError:
        pass


def _last_good(symbol: str, tf: str) -> tuple[pd.DataFrame, str] | None:
    df = _good.get((symbol, tf))
    if df is None:
        f = LAST_GOOD_DIR / f"{symbol}_{tf}.pkl"
        try:
            df = pd.read_pickle(f) if f.exists() else None
        except Exception:
            df = None
    if df is None or df.empty:
        return None
    return df, f"saved (last bar {df.index[-1]:%d-%b %H:%M})"


# ---------- option chain (Dhan only) ----------

def expiries(symbol: str) -> list[str]:
    inst = instrument(symbol)
    _need_dhan_options(inst)
    body = {"UnderlyingScrip": inst["id"], "UnderlyingSeg": inst["segment"]}
    return _cache.get(("exp", inst["symbol"]), 300,
                      lambda: dhan.post("/optionchain/expirylist", body).get("data", []))


def option_chain(symbol: str, expiry: str | None = None, strikes_each_side: int = 15, *, strict: bool = False) -> dict:
    """Dhan's chain for ``expiry`` (default: the nearest). ``strict``: an expiry Dhan doesn't list raises DataError
    instead of being sent as given."""
    inst = instrument(symbol)
    _need_dhan_options(inst)
    if strict and expiry:
        valid = expiries(symbol) or []
        if expiry not in valid:
            raise DataError(f"unknown expiry {expiry}; valid: {', '.join(valid)}")
    expiry = expiry or (expiries(symbol) or [None])[0]
    if not expiry:
        raise DataError("Dhan returned no expiries.")
    body = {"UnderlyingScrip": inst["id"], "UnderlyingSeg": inst["segment"], "Expiry": expiry}
    raw = _cache.get(("oc", inst["symbol"], expiry), 3.2, lambda: dhan.post("/optionchain", body).get("data", {}))
    spot = float(raw.get("last_price") or 0)
    rows = []
    for k, v in (raw.get("oc") or {}).items():
        rows.append({"strike": float(k), "ce": _leg(v.get("ce")), "pe": _leg(v.get("pe"))})
    rows.sort(key=lambda r: r["strike"])
    if rows and spot:
        atm_i = min(range(len(rows)), key=lambda i: abs(rows[i]["strike"] - spot))
        rows = rows[max(0, atm_i - strikes_each_side): atm_i + strikes_each_side + 1]
    return {"symbol": inst["symbol"], "expiry": expiry, "spot": spot, "lot": inst["lot"], "step": inst["step"],
            "rows": rows}


def _leg(x: dict | None) -> dict | None:
    if not x:
        return None
    g = x.get("greeks") or {}
    ltp, prev = float(x.get("last_price") or 0), float(x.get("previous_close_price") or 0)
    oi, prev_oi = int(x.get("oi") or 0), int(x.get("previous_oi") or 0)
    return {"ltp": ltp, "change": round(ltp - prev, 2) if prev else 0.0, "oi": oi, "chg_oi": oi - prev_oi,
            "volume": int(x.get("volume") or 0), "iv": round(float(x.get("implied_volatility") or 0), 2),
            "delta": g.get("delta"), "theta": g.get("theta"), "gamma": g.get("gamma"), "vega": g.get("vega"),
            "security_id": x.get("security_id")}


def _need_dhan_options(inst: dict) -> None:
    if not dhan.enabled:
        raise DataError("The option chain needs Dhan. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to .env.")
    if not inst["has_options"]:
        raise DataError(f"Option chain is available for indices here ({', '.join(INDICES)}).")
