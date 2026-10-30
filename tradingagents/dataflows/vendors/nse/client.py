"""NSE India HTTP client: the session handling nseindia.com's bot protection demands.

What the site does to a plain ``requests.get`` (observed, Oct 2026):

- The homepage answers 403 to non-browser clients (Akamai), so "hit the
  homepage for cookies" — the folk recipe — fails. Other pages (``/option-chain``)
  still answer 200 and set the cookies the ``/api`` endpoints check.
- Some ``/api`` endpoints answer without cookies, others 401/403 until a
  session exists, and a blocked request can come back 200 with an HTML page
  instead of JSON.
- Endpoints move without notice (``/api/option-chain-indices`` now 404s; the
  live chain is ``/api/option-chain-v3``), and throttling shows up as 429/503.
- Archive files (bhavcopies, constituent lists) on ``nsearchives.nseindia.com``
  are far more stable than the JSON API, and never change once published.

So this client: bootstraps cookies from pages that are not blocked, sends
browser headers, spaces requests out, retries throttles with backoff and
jitter, re-bootstraps on 401/403 or an HTML body, opens a circuit breaker after
repeated failures, and keeps every answer in a disk cache. When NSE cannot be
reached the last cached answer is served, marked stale with its age, instead of
failing the run. Failures surface as the shared ``VendorError`` types so the
router and tools treat NSE like any other vendor.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from tradingagents.dataflows.config import get_config
from tradingagents.dataflows.errors import NoMarketDataError, VendorUnavailableError
from tradingagents.dataflows.files import replace_file

logger = logging.getLogger(__name__)

NSE_HOST = "https://www.nseindia.com"
ARCHIVE_HOST = "https://nsearchives.nseindia.com"

# Pages that set the session cookies. The homepage is last: it is the one most
# often refused (403) to clients that are not a full browser.
BOOTSTRAP_PAGES = ("/option-chain", "/market-data/live-equity-market", "/")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{NSE_HOST}/",
}

# Statuses worth another attempt. 401/403 mean "no session" and trigger a
# re-bootstrap first; the rest are throttling or a transient server fault.
SESSION_STATUSES = frozenset({401, 403})
THROTTLE_STATUSES = frozenset({429, 500, 502, 503, 504})

REQUEST_TIMEOUT = 20
MIN_INTERVAL_SECONDS = 0.35     # at most ~3 requests a second, well under what NSE tolerates
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
BREAKER_THRESHOLD = 5           # consecutive failed requests before NSE is treated as down
BREAKER_COOLDOWN_SECONDS = 120


class NSEDataNotPublishedError(NoMarketDataError):
    """NSE answered that the file or record does not exist (404).

    For archive files this usually means "not published yet" or "no session that
    day", which callers check against the trading calendar.
    """


@dataclass(frozen=True)
class Fetched:
    """An NSE answer and where it came from.

    ``stale`` is True when NSE could not be reached and the cache served the
    last answer instead; ``fetched_at`` then says how old it is.
    """

    data: Any
    source: str
    fetched_at: datetime
    stale: bool = False

    @property
    def age_seconds(self) -> float:
        return (datetime.now(UTC) - self.fetched_at).total_seconds()

    def provenance(self) -> str:
        line = f"source: {self.source}; fetched {self.fetched_at:%Y-%m-%d %H:%M} UTC"
        if self.stale:
            line += f"; STALE (NSE unreachable, cached answer {self.age_seconds / 3600:.1f}h old)"
        return line


class NSEClient:
    """One throttled, self-healing session against nseindia.com and its archives."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        cache_dir: str | os.PathLike | None = None,
        min_interval: float = MIN_INTERVAL_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        backoff_base: float = BACKOFF_BASE_SECONDS,
        breaker_threshold: int = BREAKER_THRESHOLD,
        breaker_cooldown: float = BREAKER_COOLDOWN_SECONDS,
        sleep=time.sleep,
        clock=time.monotonic,
    ):
        self._session = session or requests.Session()
        self._session.headers.update(BROWSER_HEADERS)
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base
        self._breaker_threshold = breaker_threshold
        self._breaker_cooldown = breaker_cooldown
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last_request = -1e9
        self._bootstrapped = False
        self._failures = 0
        self._open_until = 0.0

    # ----------------------------------------------------------------- public

    def get_json(self, path: str, params: dict | None = None, *, ttl: float | None = 300) -> Fetched:
        """JSON from an ``/api`` path, cached for ``ttl`` seconds (None: forever)."""
        url = path if path.startswith("http") else NSE_HOST + path
        key = self._cache_key(url, params)
        cached = self._read_cache(key)
        if cached and self._fresh(cached, ttl):
            return cached
        try:
            response = self._request(url, params, expect_json=True)
            data = response.json()
        except VendorUnavailableError:
            if cached:
                logger.warning("NSE unreachable; serving cached %s", url)
                return Fetched(cached.data, cached.source, cached.fetched_at, stale=True)
            raise
        fetched = Fetched(data, url, datetime.now(UTC))
        self._write_cache(key, fetched)
        return fetched

    def get_archive(self, url: str, *, ttl: float | None = None) -> Fetched:
        """Bytes of an archive file. Published archives never change: cached forever by default."""
        if not url.startswith("http"):
            url = ARCHIVE_HOST + url
        key = self._cache_key(url, None)
        cached = self._read_cache(key, binary=True)
        if cached and self._fresh(cached, ttl):
            return cached
        try:
            response = self._request(url, None, expect_json=False)
        except VendorUnavailableError:
            if cached:
                return Fetched(cached.data, cached.source, cached.fetched_at, stale=True)
            raise
        fetched = Fetched(response.content, url, datetime.now(UTC))
        self._write_cache(key, fetched, binary=True)
        return fetched

    @property
    def breaker_open(self) -> bool:
        return self._clock() < self._open_until

    # ---------------------------------------------------------------- session

    def _bootstrap(self) -> None:
        """Collect session cookies from the first page NSE serves us."""
        for page in BOOTSTRAP_PAGES:
            try:
                self._throttle()
                response = self._session.get(NSE_HOST + page, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                logger.debug("NSE bootstrap %s failed: %s", page, exc)
                continue
            if response.status_code == 200 and self._session.cookies:
                self._bootstrapped = True
                return
        # Some endpoints answer without cookies; carry on and let the request decide.
        self._bootstrapped = True

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_request + self._min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_request = self._clock()

    def _backoff(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), BACKOFF_CAP_SECONDS)
            except ValueError:
                pass
        delay = min(self._backoff_base * 2 ** attempt, BACKOFF_CAP_SECONDS)
        return delay * (0.5 + random.random() / 2)    # jitter: callers don't retry in lockstep

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._breaker_threshold:
            self._open_until = self._clock() + self._breaker_cooldown
            logger.warning("NSE circuit breaker open for %.0fs after %d failures",
                           self._breaker_cooldown, self._failures)

    def _request(self, url: str, params: dict | None, *, expect_json: bool) -> requests.Response:
        if self.breaker_open:
            raise VendorUnavailableError("NSE is in cooldown after repeated failures")
        if expect_json and not self._bootstrapped and url.startswith(NSE_HOST):
            self._bootstrap()
        last_problem = "no attempt made"
        for attempt in range(self._max_attempts):
            self._throttle()
            try:
                response = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                last_problem = f"{type(exc).__name__}: {exc!r}"      # keeps the chain (DNS, timeout, reset) in the log
                self._sleep(self._backoff(attempt, None))
                continue
            status = response.status_code
            if status == 404:
                self._failures = 0      # NSE answered; the thing just isn't there
                raise NSEDataNotPublishedError(url, detail="NSE answered 404 (not published or moved)")
            if status in SESSION_STATUSES or (status == 200 and expect_json and _is_html(response)):
                last_problem = f"HTTP {status}" + (" (HTML instead of JSON)" if status == 200 else "")
                self._session.cookies.clear()
                self._bootstrap()
                self._sleep(self._backoff(attempt, None))
                continue
            if status in THROTTLE_STATUSES:
                last_problem = f"HTTP {status}"
                self._sleep(self._backoff(attempt, response.headers.get("Retry-After")))
                continue
            if status != 200:
                last_problem = f"HTTP {status}"
                break
            self._failures = 0
            return response
        self._record_failure()
        raise VendorUnavailableError(f"NSE request failed after retries ({last_problem}): {url}")

    # ------------------------------------------------------------------ cache

    def _cache_root(self) -> Path:
        root = self._cache_dir or Path(get_config()["data_cache_dir"]) / "nse"
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _cache_key(url: str, params: dict | None) -> str:
        raw = url + "?" + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    @staticmethod
    def _fresh(cached: Fetched, ttl: float | None) -> bool:
        return ttl is None or cached.age_seconds < ttl

    def _read_cache(self, key: str, *, binary: bool = False) -> Fetched | None:
        meta_path = self._cache_root() / f"{key}.meta.json"
        body_path = self._cache_root() / (f"{key}.bin" if binary else f"{key}.json")
        if not (meta_path.exists() and body_path.exists()):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            data = body_path.read_bytes() if binary else json.loads(body_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return Fetched(data, meta["source"], datetime.fromisoformat(meta["fetched_at"]))

    def _write_cache(self, key: str, fetched: Fetched, *, binary: bool = False) -> None:
        root = self._cache_root()
        body_path = root / (f"{key}.bin" if binary else f"{key}.json")
        if binary:
            replace_file(body_path, lambda tmp: Path(tmp).write_bytes(fetched.data))
        else:
            replace_file(body_path, lambda tmp: Path(tmp).write_text(json.dumps(fetched.data), encoding="utf-8"))
        meta = {"source": fetched.source, "fetched_at": fetched.fetched_at.isoformat()}
        replace_file(root / f"{key}.meta.json",
                     lambda tmp: Path(tmp).write_text(json.dumps(meta), encoding="utf-8"))


def _is_html(response: requests.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    return "html" in content_type or response.content[:15].lstrip().lower().startswith(b"<!doctype")


_default_client: NSEClient | None = None
_default_lock = threading.Lock()


def default_client() -> NSEClient:
    """The process-wide client, so every tool shares one session, throttle and breaker."""
    global _default_client
    with _default_lock:
        if _default_client is None:
            _default_client = NSEClient()
        return _default_client
