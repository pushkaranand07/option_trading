"""Market data: DhanHQ v2 when DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN are set, Yahoo Finance otherwise.

Yahoo is delayed and has no Indian option chains, so the option chain needs Dhan.
Dhan's limits (quotes 1/s, one unique option-chain request per 3 s) are kept by
caching every response for at least that long.
"""

from __future__ import annotations

import csv
import os
import threading
import time as _time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

IST = ZoneInfo("Asia/Kolkata")
DHAN_BASE = "https://api.dhan.co/v2"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
CACHE_DIR = Path(os.getenv("TRADINGAGENTS_CACHE_DIR") or Path.home() / ".tradingagents" / "cache")

# symbol: (display name, Dhan security id, Dhan segment, Yahoo symbol, option lot size, strike step)
INDICES = {
    "NIFTY": ("NIFTY 50", 13, "IDX_I", "^NSEI", 75, 50),
    "BANKNIFTY": ("NIFTY BANK", 25, "IDX_I", "^NSEBANK", 35, 100),
    "FINNIFTY": ("FIN NIFTY", 27, "IDX_I", "NIFTY_FIN_SERVICE.NS", 65, 50),
    "MIDCPNIFTY": ("MIDCAP SELECT", 442, "IDX_I", "NIFTY_MID_SELECT.NS", 140, 25),
    "SENSEX": ("SENSEX", 51, "IDX_I", "^BSESN", 20, 100),
}

# Offered by search when the Dhan scrip master is not loaded.
NIFTY50 = """ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL
CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HEROMOTOCO HINDALCO HINDUNILVR
ICICIBANK INDUSINDBK INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI NESTLEIND NTPC ONGC POWERGRID
RELIANCE SBILIFE SBIN SHRIRAMFIN SUNPHARMA TATACONSUM TATAMOTORS TATASTEEL TCS TECHM TITAN TRENT ULTRACEMCO
WIPRO PNB""".split()


class DataError(Exception):
    pass


class _TTLCache:
    def __init__(self):
        self._d: dict = {}
        self._lock = threading.Lock()

    def get(self, key, ttl: float, fn):
        with self._lock:
            hit = self._d.get(key)
            if hit and _time.monotonic() - hit[0] < ttl:
                return hit[1]
        value = fn()
        with self._lock:
            self._d[key] = (_time.monotonic(), value)
        return value


_cache = _TTLCache()


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
        r = requests.post(
            f"{DHAN_BASE}{path}", json=body, timeout=15,
            headers={"access-token": self.token, "client-id": self.client_id,
                     "Content-Type": "application/json", "Accept": "application/json"},
        )
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


def _load_scrip_master() -> dict[str, tuple[int, str]]:
    """NSE cash-market equities: trading symbol -> (security id, company name). Refreshed daily."""
    path = CACHE_DIR / "dhan-scrip-master.csv"
    if not path.exists() or datetime.fromtimestamp(path.stat().st_mtime).date() != datetime.now().date():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        r = requests.get(SCRIP_MASTER_URL, timeout=60)
        r.raise_for_status()
        path.write_bytes(r.content)
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
            _equities = _cache.get("scrip", 3600, _load_scrip_master)
        except Exception:
            _equities = {}
    return _equities


# ---------- instruments ----------

def instrument(symbol: str) -> dict:
    s = symbol.strip().upper()
    if s in INDICES:
        name, sid, seg, yahoo, lot, step = INDICES[s]
        return {"symbol": s, "name": name, "kind": "INDEX", "id": sid, "segment": seg, "yahoo": yahoo,
                "lot": lot, "step": step, "has_options": True}
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
                    out[i["symbol"]] = _quote_row(i, ltp, prev, row.get("ohlc") or {}, "dhan")
        except DataError:
            pass
    for i in insts:
        if i["symbol"] not in out:
            q = _cache.get(("yq", i["yahoo"]), 15, lambda i=i: _yahoo_quote(i))
            if q:
                out[i["symbol"]] = q
    return out


def _quote_row(inst, ltp, prev, ohlc, source):
    chg = ltp - prev if prev else 0.0
    return {"symbol": inst["symbol"], "name": inst["name"], "ltp": round(ltp, 2), "prev_close": round(prev, 2),
            "change": round(chg, 2), "change_pct": round(chg / prev * 100, 2) if prev else 0.0,
            "open": ohlc.get("open"), "high": ohlc.get("high"), "low": ohlc.get("low"), "source": source}


def _yahoo_quote(inst) -> dict | None:
    try:
        fi = yf.Ticker(inst["yahoo"]).fast_info
        ltp, prev = float(fi["last_price"]), float(fi["previous_close"])
        ohlc = {"open": round(float(fi["open"]), 2), "high": round(float(fi["day_high"]), 2),
                "low": round(float(fi["day_low"]), 2)}
        return _quote_row(inst, ltp, prev, ohlc, "yahoo")
    except Exception:
        return None


# ---------- candles ----------

# timeframe: (Dhan interval or None for daily, days of history, Yahoo period, Yahoo interval)
TIMEFRAMES = {
    "1m": ("1", 4, "5d", "1m"),
    "5m": ("5", 59, "60d", "5m"),   # ~60 sessions: also the backtest window
    "15m": ("15", 59, "60d", "15m"),
    "1h": ("60", 89, "3mo", "60m"),
    "1D": (None, 730, "2y", "1d"),
}


def candles(symbol: str, tf: str = "5m") -> tuple[pd.DataFrame, str]:
    inst = instrument(symbol)
    if tf not in TIMEFRAMES:
        raise DataError(f"Unknown timeframe {tf}")
    ttl = 4 if tf != "1D" else 20
    return _cache.get(("c", inst["symbol"], tf), ttl, lambda: _candles(inst, tf))


def _candles(inst: dict, tf: str) -> tuple[pd.DataFrame, str]:
    interval, days, y_period, y_interval = TIMEFRAMES[tf]
    if dhan.enabled and inst["id"] is not None:
        now = datetime.now(IST)
        body = {"securityId": str(inst["id"]), "exchangeSegment": inst["segment"],
                "instrument": inst["kind"], "oi": False}
        try:
            if interval:
                body |= {"interval": interval,
                         "fromDate": (now - timedelta(days=days)).strftime("%Y-%m-%d 09:00:00"),
                         "toDate": (now + timedelta(days=1)).strftime("%Y-%m-%d 00:00:00")}
                data = dhan.post("/charts/intraday", body)
            else:
                body |= {"expiryCode": 0, "fromDate": (now - timedelta(days=days)).strftime("%Y-%m-%d"),
                         "toDate": (now + timedelta(days=1)).strftime("%Y-%m-%d")}
                data = dhan.post("/charts/historical", body)
            if data.get("timestamp"):
                df = pd.DataFrame({k: data[k] for k in ("open", "high", "low", "close", "volume")},
                                  index=pd.to_datetime(data["timestamp"], unit="s", utc=True).tz_convert(IST))
                return df.astype(float), "dhan"
        except DataError:
            pass
    df = yf.Ticker(inst["yahoo"]).history(period=y_period, interval=y_interval, auto_adjust=False)
    if df.empty:
        raise DataError(f"No price data for {inst['symbol']}")
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
    df.index = df.index.tz_convert(IST) if df.index.tz else df.index.tz_localize(IST)
    return df.astype(float), "yahoo"


# ---------- option chain (Dhan only) ----------

def expiries(symbol: str) -> list[str]:
    inst = instrument(symbol)
    _need_dhan_options(inst)
    body = {"UnderlyingScrip": inst["id"], "UnderlyingSeg": inst["segment"]}
    return _cache.get(("exp", inst["symbol"]), 300,
                      lambda: dhan.post("/optionchain/expirylist", body).get("data", []))


def option_chain(symbol: str, expiry: str | None = None, strikes_each_side: int = 15) -> dict:
    inst = instrument(symbol)
    _need_dhan_options(inst)
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


def dhan_profile() -> dict | None:
    if not dhan.enabled:
        return None
    try:
        r = requests.get(f"{DHAN_BASE}/profile", headers={"access-token": dhan.token}, timeout=10)
        return r.json() if r.status_code == 200 else {"error": r.text[:200]}
    except Exception as exc:
        return {"error": str(exc)}
