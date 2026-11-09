"""The one door to Dhan: public market data only, never the user's account (audit 2026-11, step 1.2a).

Every Dhan request goes through ``request``. It allows only the market-data endpoints below (quotes / LTP / OHLC,
intraday and historical charts, option chain, expiry list, the public security master). Anything else (orders,
trade book, positions, holdings, funds / margins, ledger, eDIS, kill switch, super / forever orders, profile, any
unknown path or host) raises DhanAccountAccessBlocked BEFORE a request is made, unless DHAN_ACCOUNT_ACCESS=1 is set
in the environment (read at call time; never set by this project). Each call is logged as one line (time, method,
endpoint, status; never the token or client id) to DHAN_CALL_LOG (default ``_audit/dhan_calls.log``), and calls are
spaced at least MIN_INTERVAL seconds apart across all threads.
"""

from __future__ import annotations

import os
import posixpath
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

API = "https://api.dhan.co/v2"
ROOT = Path(__file__).resolve().parent.parent
LOG = Path(os.getenv("DHAN_CALL_LOG") or ROOT / "_audit" / "dhan_calls.log")
MIN_INTERVAL = 1.0
# (method, host, path): the only requests allowed without DHAN_ACCOUNT_ACCESS=1.
ALLOWED = {
    ("POST", "api.dhan.co", "/v2/marketfeed/ltp"),
    ("POST", "api.dhan.co", "/v2/marketfeed/ohlc"),
    ("POST", "api.dhan.co", "/v2/marketfeed/quote"),
    ("POST", "api.dhan.co", "/v2/charts/intraday"),
    ("POST", "api.dhan.co", "/v2/charts/historical"),
    ("POST", "api.dhan.co", "/v2/optionchain"),
    ("POST", "api.dhan.co", "/v2/optionchain/expirylist"),
    ("GET", "images.dhan.co", "/api-data/api-scrip-master.csv"),
    ("GET", "images.dhan.co", "/api-data/api-scrip-master-detailed.csv"),
}

_lock = threading.Lock()
_last = 0.0
_sleep = time.sleep
_monotonic = time.monotonic


class DhanAccountAccessBlocked(PermissionError):
    """A Dhan request outside the market-data allowlist was refused before it was sent."""


def _target(method: str, url_or_path: str) -> tuple[str, str, str, str]:
    """(METHOD, host, checked path, url to send). The checked path is the normalised one; when the raw URL differs
    from it in any way (a query, a fragment, "..", "//", a trailing slash), the path returned is a marker that is
    never allowed, so what is checked is exactly what is sent."""
    url = url_or_path if "://" in url_or_path else API + url_or_path
    parts = urlsplit(url)
    path = posixpath.normpath(parts.path) if parts.path else "/"     # "/v2/marketfeed/../orders" -> "/v2/orders"
    if parts.query or parts.fragment or parts.path != path:
        path = f"<not exact: {url_or_path}>"
    return method.upper(), (parts.hostname or "").lower(), path, url


def allowed(method: str, url_or_path: str) -> bool:
    m, host, path, _ = _target(method, url_or_path)
    return (m, host, path) in ALLOWED


def _log(method: str, host: str, path: str, outcome: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t{method}\t{host}{path}\t{outcome}\n")
    except OSError:
        pass                                   # logging must never break market data; the guard itself still applies


def request(method: str, url_or_path: str, *, token: str = "", client_id: str = "", timeout: float = 15,
            **kwargs) -> requests.Response:
    """Send one Dhan request if it is allowed; ``token`` / ``client_id`` become Dhan's auth headers."""
    global _last
    m, host, path, url = _target(method, url_or_path)
    if (m, host, path) not in ALLOWED and os.environ.get("DHAN_ACCOUNT_ACCESS") != "1":
        _log(m, host, path, "BLOCKED")
        raise DhanAccountAccessBlocked(f"Dhan {m} {host}{path} is not a market-data endpoint: blocked before sending")
    headers = dict(kwargs.pop("headers", None) or {})
    if host == "api.dhan.co":
        headers |= {"access-token": token, "client-id": client_id, "Content-Type": "application/json", "Accept": "application/json"}
    with _lock:                                # at most one Dhan request per MIN_INTERVAL, across threads
        wait = MIN_INTERVAL - (_monotonic() - _last)
        if wait > 0:
            _sleep(wait)
        try:
            r = requests.request(m, url, headers=headers, timeout=timeout, **kwargs)
        finally:
            _last = _monotonic()
    _log(m, host, path, f"HTTP {getattr(r, 'status_code', '?')}")
    return r
