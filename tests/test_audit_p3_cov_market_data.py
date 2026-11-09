"""Phase 3 coverage: market_data's Dhan paths, candle fallbacks, scrip master parsing, instrument lookup, the expiries
cache and the option chain's shape, all behind a fake Dhan guard transport (``webapp.dhan_guard.requests.request``)
and a fake Yahoo (``yf.Ticker``). The Dhan keys are fake and set in-process only; no request leaves the machine."""

from __future__ import annotations

import os
from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

from tradingagents.dataflows.vendors.nse.calendar import IST as PYTZ_IST, NSECalendar
from webapp import dhan_guard, market_data as md, signals

IST = ZoneInfo("Asia/Kolkata")
CAL = NSECalendar({})

SCRIP_HEADER = ("SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,"
                "SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_SERIES,SM_SYMBOL_NAME\n")
SCRIP_ROWS = [
    "NSE,D,35001,OPTIDX,0,NIFTY-Nov2026-25000-CE,75.0,NIFTY CE,NA,",
    "NSE,D,35002,OPTIDX,0,NIFTY-Nov2026-25000-PE,75.0,NIFTY PE,NA,",
    "NSE,D,35003,OPTIDX,0,BANKNIFTY-Nov2026-50000-CE,abc,BN CE,NA,",       # unreadable lot: skipped
    "NSE,E,2885,EQUITY,0,RELIANCE,1.0,Reliance,EQ,RELIANCE INDUSTRIES LTD",
    "NSE,E,1333,EQUITY,0,HDFCBANK,1.0,HDFC Bank,EQ,HDFC BANK LTD",
    "NSE,E,11536,EQUITY,0,TCS,1.0,TCS CUSTOM,EQ,",                           # no SM name: the custom symbol
    "NSE,E,9999,EQUITY,0,SOMEBOND,1.0,x,N1,SOME BOND",                       # not EQ series
    "BSE,E,500325,EQUITY,0,RELIANCE,1.0,x,A,RELIANCE BSE",                   # BSE: ignored
]
SCRIP_CSV = (SCRIP_HEADER + "\n".join(SCRIP_ROWS) + "\n").encode()


class Resp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self.content = status, body, content

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class Transport:
    """Stands in for requests.request under the Dhan guard: answers by path, records every call."""

    def __init__(self):
        self.calls: list[dict] = []
        self.routes: dict = {}

    def __call__(self, method, url, headers=None, timeout=None, **kw):
        path = urlsplit(url).path
        self.calls.append({"method": method, "url": url, "path": path, "headers": headers or {}, "json": kw.get("json")})
        handler = self.routes.get(path)
        if handler is None:
            raise AssertionError(f"unexpected {method} {url}")
        r = handler(kw.get("json")) if callable(handler) else handler
        if isinstance(r, list):
            r = r.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def paths(self):
        return [c["path"] for c in self.calls]


def ts(day: str) -> int:
    return int(pd.Timestamp(day, tz=IST).timestamp())


def daily(closes: dict[str, float]) -> dict:
    c = list(closes.values())
    return {"timestamp": [ts(d) for d in closes], "open": c, "high": c, "low": c, "close": c, "volume": [1.0] * len(c)}


class _Ticker:
    """Fake yfinance: ``history`` answers the class's frame (or raises), ``fast_info`` the class's dict."""
    frame: pd.DataFrame | Exception = pd.DataFrame()
    fast: dict | Exception = {}
    asked: list = []

    def __init__(self, symbol):
        self.symbol = symbol
        _Ticker.asked.append(symbol)

    def history(self, **kw):
        if isinstance(_Ticker.frame, Exception):
            raise _Ticker.frame
        return _Ticker.frame.copy()

    @property
    def fast_info(self):
        if isinstance(_Ticker.fast, Exception):
            raise _Ticker.fast
        return _Ticker.fast


def stamp_scrip_master(*when):
    """Give the downloaded scrip master the fake clock's date (its mtime decides whether it is downloaded again)."""
    t = datetime(*when, tzinfo=IST).timestamp()
    os.utime(md.CACHE_DIR / "dhan-scrip-master.csv", (t, t))


def at(monkeypatch, *a):
    moment = PYTZ_IST.localize(datetime(*a))
    monkeypatch.setattr("webapp.signals.now_ist", lambda: moment)
    monkeypatch.setattr("webapp.timeutil.now_ist", lambda: moment)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Fresh caches, a temp cache dir, the fake transport, fake Yahoo and the NSE calendar; Dhan off until ``keys``."""
    monkeypatch.setattr(md, "_cache", md._TTLCache())
    monkeypatch.setattr(md, "_equities", {})
    monkeypatch.setattr(md, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(md, "LAST_GOOD_DIR", tmp_path / "good")
    monkeypatch.setattr(md, "_good", {})
    monkeypatch.setattr(md, "_good_saved", {})
    monkeypatch.setattr(dhan_guard, "_sleep", lambda s: None)
    monkeypatch.setattr(dhan_guard, "LOG", tmp_path / "dhan_calls.log")
    t = Transport()
    t.routes["/api-data/api-scrip-master.csv"] = Resp(200, content=SCRIP_CSV)
    monkeypatch.setattr(dhan_guard.requests, "request", t)
    monkeypatch.setattr(_Ticker, "frame", pd.DataFrame())
    monkeypatch.setattr(_Ticker, "fast", {})
    monkeypatch.setattr(_Ticker, "asked", [])
    monkeypatch.setattr(md.yf, "Ticker", _Ticker)
    monkeypatch.setattr(signals, "nse_calendar", lambda: CAL)
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    monkeypatch.setattr(md, "dhan", md.Dhan())
    at(monkeypatch, 2026, 11, 3, 11, 0)                          # a Tuesday, market open
    return t


@pytest.fixture
def keys(world, monkeypatch):
    """Fake Dhan keys, in this process only; a new Dhan reads them."""
    monkeypatch.setenv("DHAN_CLIENT_ID", "fake-client")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(md, "dhan", md.Dhan())
    assert md.dhan.enabled
    return world


# ---------- Dhan.post ----------

@pytest.mark.unit
def test_post_sends_the_fake_keys_as_dhan_headers_and_returns_the_body(keys):
    keys.routes["/v2/marketfeed/ohlc"] = Resp(200, {"status": "success", "data": {"IDX_I": {}}})
    assert md.dhan.post("/marketfeed/ohlc", {"IDX_I": [13]}) == {"status": "success", "data": {"IDX_I": {}}}
    call = keys.calls[-1]
    assert call["method"] == "POST" and call["url"] == "https://api.dhan.co/v2/marketfeed/ohlc"
    assert call["headers"]["access-token"] == "fake-token" and call["headers"]["client-id"] == "fake-client"
    assert call["json"] == {"IDX_I": [13]}
    assert "fake-token" not in dhan_guard.LOG.read_text(encoding="utf-8")       # the log never holds the token


@pytest.mark.unit
@pytest.mark.parametrize(("resp", "message"), [
    (Resp(502, None), "Dhan /marketfeed/ohlc: HTTP 502"),
    (Resp(400, {"errorCode": "DH-902", "errorMessage": "x"}), "no Data API subscription"),
    (Resp(401, {"status": "failure", "remarks": {"error_code": "807", "error_message": "expired"}}), "rejected the access token"),
    (Resp(200, {"status": "failure", "remarks": {"error_code": "DH-905", "error_message": "Bad segment"}}), "Dhan: Bad segment"),
    (Resp(500, {"errorMessage": "Server busy"}), "Dhan: Server busy"),
])
def test_post_turns_dhan_errors_into_plain_data_errors(keys, resp, message):
    keys.routes["/v2/marketfeed/ohlc"] = resp
    with pytest.raises(md.DataError, match=message):
        md.dhan.post("/marketfeed/ohlc", {})


@pytest.mark.unit
def test_an_account_path_is_blocked_before_anything_is_sent(keys):
    with pytest.raises(dhan_guard.DhanAccountAccessBlocked):
        md.dhan.post("/orders", {"qty": 1})
    assert keys.calls == []


# ---------- scrip master, lots, equities, instrument, search ----------

@pytest.mark.unit
def test_scrip_master_is_downloaded_once_a_day_and_parsed_once(keys):
    assert md.index_lots() == {"NIFTY": 75}
    assert keys.paths() == ["/api-data/api-scrip-master.csv"]
    side = md.CACHE_DIR / "dhan-scrip-master.lots.json"
    assert side.exists()
    stamp_scrip_master(2026, 11, 3, 8, 0)                        # downloaded earlier today (the fake clock's day)
    md._cache = md._TTLCache()                                   # a restart: today's file is reused
    assert md.index_lots() == {"NIFTY": 75}
    assert len(keys.calls) == 1


@pytest.mark.unit
def test_a_stale_side_file_is_parsed_again_and_yesterdays_file_downloaded_again(keys):
    md.index_lots()
    stamp_scrip_master(2026, 11, 3, 8, 0)
    side = md.CACHE_DIR / "dhan-scrip-master.lots.json"
    side.write_text('{"stamp": 1, "data": {"NIFTY": 1}}', encoding="utf-8")   # another file's parse
    md._cache = md._TTLCache()
    assert md.index_lots() == {"NIFTY": 75}
    assert len(keys.calls) == 1
    stamp_scrip_master(2026, 11, 2, 9, 0)                        # yesterday's file
    md._cache = md._TTLCache()
    md.index_lots()
    assert keys.paths().count("/api-data/api-scrip-master.csv") == 2


@pytest.mark.unit
def test_index_lots_is_empty_and_the_table_applies_when_the_download_fails(keys):
    keys.routes["/api-data/api-scrip-master.csv"] = Resp(503)
    assert md.index_lots() == {}
    assert md.instrument("NIFTY")["lot"] == md.INDICES["NIFTY"][4]


@pytest.mark.unit
def test_instrument_reads_ids_and_names_from_the_scrip_master(keys):
    nifty = md.instrument(" nifty ")
    assert nifty == {"symbol": "NIFTY", "name": "NIFTY 50", "kind": "INDEX", "id": 13, "segment": "IDX_I",
                     "yahoo": "^NSEI", "lot": 75, "step": 50, "has_options": True}
    assert md.instrument("BANKNIFTY")["lot"] == 30                 # its only row had an unreadable lot
    rel = md.instrument("reliance")
    assert (rel["id"], rel["name"], rel["segment"], rel["yahoo"], rel["has_options"]) == (
        2885, "Reliance Industries Ltd", "NSE_EQ", "RELIANCE.NS", False)
    assert md.instrument("TCS")["name"] == "Tcs Custom"
    assert md.instrument("SOMEBOND")["id"] is None and md.instrument("SOMEBOND")["name"] == "SOMEBOND"
    assert set(md.equities()) == {"RELIANCE", "HDFCBANK", "TCS"}


@pytest.mark.unit
def test_equities_stay_empty_when_the_scrip_master_cannot_be_read(keys):
    keys.routes["/api-data/api-scrip-master.csv"] = requests.ConnectionError("offline")
    assert md.equities() == {}
    assert md.instrument("RELIANCE")["id"] is None


@pytest.mark.unit
def test_search_uses_the_scrip_master_with_dhan_and_nifty50_without(world, monkeypatch):
    assert md.search("  ") == []
    hits = md.search("bank")
    assert hits[0] == {"symbol": "BANKNIFTY", "name": "NIFTY BANK", "kind": "INDEX"}
    assert {"symbol": "AXISBANK", "name": "AXISBANK", "kind": "EQUITY"} in hits     # the NIFTY 50 fallback
    assert world.calls == []                                          # no Dhan, no download
    assert md.search("zz9") == [{"symbol": "ZZ9", "name": "ZZ9", "kind": "EQUITY"}]
    assert md.search("@@") == []
    assert len(md.search("a", limit=3)) == 3

    monkeypatch.setenv("DHAN_CLIENT_ID", "fake-client")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-token")
    monkeypatch.setattr(md, "dhan", md.Dhan())
    hits = md.search("industries")
    assert hits == [{"symbol": "RELIANCE", "name": "Reliance Industries Ltd", "kind": "EQUITY"}]
    assert [h["symbol"] for h in md.search("hdfc")] == ["HDFCBANK"]


# ---------- quotes ----------

def _ohlc(rows: dict) -> Resp:
    return Resp(200, {"status": "success", "data": rows})


@pytest.mark.unit
def test_dhan_quotes_use_the_bars_previous_close_and_warn_when_dhan_differs(keys):
    keys.routes["/v2/charts/historical"] = Resp(200, daily({"2026-10-30": 24800.0, "2026-11-02": 24950.0,
                                                            "2026-11-03": 25010.0}))
    keys.routes["/v2/marketfeed/ohlc"] = _ohlc({
        "IDX_I": {"13": {"last_price": 25000.0, "ohlc": {"open": 24960, "high": 25050, "low": 24940, "close": 24000}}},
        "NSE_EQ": {"2885": {"last_price": 1400.0, "ohlc": {"open": 1390, "high": 1410, "low": 1385, "close": 24950}}},
    })
    out = md.quotes(["NIFTY", "RELIANCE", "NIFTY", ""])
    n = out["NIFTY"]
    assert n["source"] == "dhan" and n["ltp"] == 25000.0 and n["prev_close"] == 24950.0
    assert n["prev_close_source"] == "bars (dhan)" and n["change"] == 50.0 and n["change_pct"] == 0.2
    assert "differs between sources" in n["prev_close_warning"] and "24,000.00" in n["prev_close_warning"]
    assert (n["open"], n["high"], n["low"]) == (24960, 25050, 24940)
    ohlc_bodies = [c["json"] for c in keys.calls if c["path"] == "/v2/marketfeed/ohlc"]
    assert ohlc_bodies == [{"IDX_I": [13], "NSE_EQ": [2885]}]
    hist = [c["json"] for c in keys.calls if c["path"] == "/v2/charts/historical"]
    assert {"securityId": "13", "exchangeSegment": "IDX_I", "instrument": "INDEX", "oi": False, "expiryCode": 0} \
        .items() <= hist[0].items()

    calls = len(keys.calls)
    assert md.quotes(["NIFTY", "RELIANCE"]) == out                    # cached: Dhan's 1 request / s is kept
    assert len(keys.calls) == calls


@pytest.mark.unit
def test_a_rejected_dhan_quote_falls_back_to_yahoo(keys, monkeypatch):
    keys.routes["/v2/charts/historical"] = Resp(200, {"timestamp": []})   # no Dhan bars, no Yahoo bars either
    keys.routes["/v2/marketfeed/ohlc"] = Resp(401, {"errorCode": "DH-901"})
    monkeypatch.setattr(_Ticker, "fast", {"last_price": 25000.0, "previous_close": 24900.0, "open": 24950.123,
                                          "day_high": 25100.0, "day_low": 24900.0})
    row = md.quotes(["NIFTY"])["NIFTY"]
    assert row["source"] == "yahoo" and row["prev_close"] == 24900.0 and row["prev_close_source"] == "yahoo"
    assert row["open"] == 24950.12 and "prev_close_warning" not in row


@pytest.mark.unit
def test_no_quote_from_any_source_leaves_the_symbol_out(world, monkeypatch):
    monkeypatch.setattr(_Ticker, "fast", RuntimeError("Yahoo down"))
    monkeypatch.setattr(_Ticker, "frame", RuntimeError("Yahoo down"))
    assert md.quotes(["NIFTY"]) == {}


@pytest.mark.unit
def test_an_invalid_previous_close_is_never_shown(world, monkeypatch):
    monkeypatch.setattr(_Ticker, "fast", {"last_price": 100.0, "previous_close": float("nan"), "open": 1,
                                          "day_high": 1, "day_low": 1})
    row = md.quotes(["INFY"])["INFY"]
    assert row["prev_close"] is None and row["prev_close_source"] == "none" and row["change"] == 0.0
    assert row["prev_close_warning"].startswith("No valid previous close")


@pytest.mark.unit
def test_quotes_survive_an_unknown_session(world, monkeypatch):
    def broken():
        raise RuntimeError("calendar down")
    monkeypatch.setattr(signals, "nse_calendar", broken)
    monkeypatch.setattr(_Ticker, "fast", {"last_price": 110.0, "previous_close": 100.0, "open": 1,
                                          "day_high": 1, "day_low": 1})
    row = md.quotes(["INFY", "TCS"])["INFY"]
    assert row["prev_close"] == 100.0 and row["change_pct"] == 10.0 and row["prev_close_source"] == "yahoo"


@pytest.mark.unit
def test_previous_close_falls_back_to_dhan_daily_when_the_bars_miss_the_session(keys, monkeypatch):
    # the chart's own 1D bars (Yahoo, already held) miss 2 Nov; Dhan's daily history has it
    held = pd.DataFrame({"close": [24800.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-10-30", tz=IST)]))
    md._cache.get(("c", "NIFTY", "1D"), 20, lambda: (held, "yahoo"))
    keys.routes["/v2/charts/historical"] = Resp(200, daily({"2026-10-30": 24800.0, "2026-11-02": 24950.0}))
    inst = md.instrument("NIFTY")
    assert md.prev_close(inst, date(2026, 11, 3), vendor=24951.0, vendor_source="dhan") == (24950.0, "dhan daily", None)
    md._cache = md._TTLCache()
    keys.routes["/v2/charts/historical"] = Resp(500, {"errorMessage": "busy"})
    assert md.prev_close(md.instrument("NIFTY"), date(2026, 11, 3), vendor=None) == (None, "none", None)


# ---------- candles ----------

def _yahoo_frame(days=("2026-11-03 09:15", "2026-11-03 09:20"), tz=None):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days])
    idx = idx.tz_localize(tz) if tz else idx
    n = len(days)
    return pd.DataFrame({"Open": [1.0] * n, "High": [2.0] * n, "Low": [0.5] * n, "Close": [1.5] * n,
                         "Volume": [10] * n, "Adj Close": [1.5] * n}, index=idx)


@pytest.mark.unit
def test_dhan_intraday_bars_come_first(keys):
    keys.routes["/v2/charts/intraday"] = Resp(200, {"timestamp": [ts("2026-11-03 09:15"), ts("2026-11-03 09:20")],
                                                    "open": [1, 2], "high": [2, 3], "low": [0, 1], "close": [1, 2],
                                                    "volume": [5, 6]})
    df, source = md.candles("nifty", "5m")
    assert source == "dhan" and list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df["close"].tolist() == [1.0, 2.0] and str(df.index.tz) == "Asia/Kolkata"
    body = keys.calls[-1]["json"]
    assert body["interval"] == "5" and body["fromDate"].endswith("09:00:00") and body["instrument"] == "INDEX"
    md.candles("NIFTY", "5m")
    assert keys.paths().count("/v2/charts/intraday") == 1            # cached for 4 s


@pytest.mark.unit
@pytest.mark.parametrize("dhan_answer", [Resp(200, {"timestamp": []}), Resp(400, {"errorCode": "DH-905", "errorMessage": "x"})])
def test_no_dhan_bars_or_a_dhan_error_falls_back_to_yahoo(keys, monkeypatch, dhan_answer):
    keys.routes["/v2/charts/intraday"] = dhan_answer
    monkeypatch.setattr(_Ticker, "frame", _yahoo_frame())             # a naive index is taken as IST
    df, source = md.candles("NIFTY", "15m")
    assert source == "yahoo" and df["close"].tolist() == [1.5, 1.5]
    assert df.index[0] == pd.Timestamp("2026-11-03 09:15", tz=IST) and "adj close" not in df.columns
    assert (md.LAST_GOOD_DIR / "NIFTY_15m.pkl").exists()


@pytest.mark.unit
def test_an_equity_without_an_id_skips_dhan(keys, monkeypatch):
    monkeypatch.setattr(_Ticker, "frame", _yahoo_frame(tz="UTC"))
    df, source = md.candles("SOMEBOND", "1h")
    assert source == "yahoo" and _Ticker.asked == ["SOMEBOND.NS"]
    assert df.index[0] == pd.Timestamp("2026-11-03 09:15", tz="UTC")
    assert "/v2/charts/intraday" not in keys.paths()


@pytest.mark.unit
def test_unknown_timeframe_is_a_data_error(world):
    with pytest.raises(md.DataError, match="Unknown timeframe 2h"):
        md.candles("NIFTY", "2h")


@pytest.mark.unit
def test_saved_bars_from_disk_when_yahoo_fails_and_memory_is_empty(world, monkeypatch):
    monkeypatch.setattr(_Ticker, "frame", _yahoo_frame())
    md.candles("INFY", "5m")
    md._good.clear()                                                   # a restart: only the disk copy is left
    md._cache = md._TTLCache()
    monkeypatch.setattr(_Ticker, "frame", RuntimeError("no internet"))
    df, source = md.candles("INFY", "5m")
    assert source == "saved (last bar 03-Nov 09:20)" and len(df) == 2


@pytest.mark.unit
def test_a_damaged_saved_file_is_a_clear_error(world):
    md.LAST_GOOD_DIR.mkdir(parents=True)
    (md.LAST_GOOD_DIR / "INFY_5m.pkl").write_bytes(b"not a pickle")
    with pytest.raises(md.DataError, match="No price data for INFY"):
        md.candles("INFY", "5m")


@pytest.mark.unit
def test_bars_are_written_to_disk_at_most_once_a_minute(world):
    df = _yahoo_frame().rename(columns=str.lower)
    md._remember("X", "5m", df)
    f = md.LAST_GOOD_DIR / "X_5m.pkl"
    f.unlink()
    md._remember("X", "5m", df.iloc[:1])
    assert not f.exists() and len(md._good[("X", "5m")]) == 1        # memory updated, disk not rewritten


@pytest.mark.unit
def test_bar_age_and_stale_bars():
    df = pd.DataFrame({"close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-11-03 10:00", tz=IST)]))
    now = datetime(2026, 11, 3, 10, 15, tzinfo=IST)
    assert md.bar_age(df, now) == 900 and md.bar_age(pd.DataFrame(), now) is None and md.bar_age(None) is None
    assert md.stale_bars(df, "5m", True, now) == 900                   # > 600 s while open: stale
    assert md.stale_bars(df, "15m", True, now) is None                 # within 1800 s
    assert md.stale_bars(df, "5m", False, now) is None                 # closed market: never stale
    assert md.stale_bars(df, "1D", True, now) is None
    assert md.stale_bars(pd.DataFrame(), "5m", True, now) is None


# ---------- expiries and the option chain ----------

def _leg(ltp, prev, oi, prev_oi, iv=12.346, sid=1):
    return {"last_price": ltp, "previous_close_price": prev, "oi": oi, "previous_oi": prev_oi, "volume": 7,
            "implied_volatility": iv, "greeks": {"delta": 0.5, "theta": -3, "gamma": 0.001, "vega": 9},
            "security_id": sid}


def _chain_body(spot=25010.0):
    oc = {f"{k:.6f}": {"ce": _leg(100 + k / 1000, 90, 1000, 400), "pe": _leg(80, 0, 500, 500)}
          for k in range(24800, 25250, 50)}
    oc["25300.000000"] = {"ce": _leg(5, 6, 10, 0), "pe": None}
    return {"status": "success", "data": {"last_price": spot, "oc": oc}}


@pytest.mark.unit
def test_expiries_need_dhan_and_an_index(world, keys, monkeypatch):
    keys.routes["/v2/optionchain/expirylist"] = Resp(200, {"status": "success", "data": ["2026-11-10", "2026-11-17"]})
    assert md.expiries("NIFTY") == ["2026-11-10", "2026-11-17"]
    assert md.expiries("NIFTY") == ["2026-11-10", "2026-11-17"]
    assert keys.paths().count("/v2/optionchain/expirylist") == 1       # cached 300 s
    assert keys.calls[-1]["json"] == {"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I"}
    with pytest.raises(md.DataError, match="available for indices"):
        md.expiries("RELIANCE")
    monkeypatch.setattr(md, "dhan", type("NoDhan", (), {"enabled": False})())
    with pytest.raises(md.DataError, match="needs Dhan"):
        md.option_chain("NIFTY")


@pytest.mark.unit
def test_option_chain_is_shaped_around_the_money(keys):
    keys.routes["/v2/optionchain/expirylist"] = Resp(200, {"status": "success", "data": ["2026-11-10", "2026-11-17"]})
    keys.routes["/v2/optionchain"] = Resp(200, _chain_body())
    ch = md.option_chain("NIFTY", strikes_each_side=2)
    assert (ch["symbol"], ch["expiry"], ch["spot"], ch["lot"], ch["step"]) == ("NIFTY", "2026-11-10", 25010.0, 75, 50)
    assert [r["strike"] for r in ch["rows"]] == [24900.0, 24950.0, 25000.0, 25050.0, 25100.0]
    ce = ch["rows"][2]["ce"]
    assert ce == {"ltp": 125.0, "change": 35.0, "oi": 1000, "chg_oi": 600, "volume": 7, "iv": 12.35, "delta": 0.5,
                  "theta": -3, "gamma": 0.001, "vega": 9, "security_id": 1}
    assert ch["rows"][2]["pe"]["change"] == 0.0                        # no previous close: no change
    assert keys.calls[-1]["json"] == {"UnderlyingScrip": 13, "UnderlyingSeg": "IDX_I", "Expiry": "2026-11-10"}

    full = md.option_chain("NIFTY", "2026-11-10")                      # same key, within 3.2 s: not refetched
    assert keys.paths().count("/v2/optionchain") == 1
    assert full["rows"][-1] == {"strike": 25300.0, "ce": full["rows"][-1]["ce"], "pe": None}


@pytest.mark.unit
def test_option_chain_strict_expiry_and_no_expiries(keys):
    keys.routes["/v2/optionchain/expirylist"] = Resp(200, {"status": "success", "data": ["2026-11-10"]})
    with pytest.raises(md.DataError, match="unknown expiry 2026-12-31; valid: 2026-11-10"):
        md.option_chain("NIFTY", "2026-12-31", strict=True)
    assert "/v2/optionchain" not in keys.paths()
    keys.routes["/v2/optionchain"] = Resp(200, {"status": "success", "data": {"last_price": 0, "oc": {}}})
    ch = md.option_chain("NIFTY", "2026-12-31")                        # lenient: sent as given
    assert ch["expiry"] == "2026-12-31" and ch["rows"] == [] and ch["spot"] == 0.0
    md._cache = md._TTLCache()
    keys.routes["/v2/optionchain/expirylist"] = Resp(200, {"status": "success", "data": []})
    with pytest.raises(md.DataError, match="Dhan returned no expiries"):
        md.option_chain("BANKNIFTY")


# ---------- the cache ----------

@pytest.mark.unit
def test_a_failed_lookup_is_kept_only_for_miss_ttl(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(md._time, "monotonic", lambda: clock[0])
    c, calls = md._TTLCache(), []
    fn = lambda: calls.append(1)                                      # noqa: E731  answers None
    c.get("k", 600, fn, miss_ttl=30)
    clock[0] += 10
    c.get("k", 600, fn, miss_ttl=30)
    assert len(calls) == 1
    clock[0] += 25
    c.get("k", 600, fn, miss_ttl=30)
    assert len(calls) == 2
    assert c.peek("k", 600) is None and c.peek("nothing", 600) is None
    c.get("v", 5, lambda: "x")
    assert c.peek("v", 5) == "x"
    clock[0] += 6
    assert c.peek("v", 5) is None


@pytest.mark.unit
def test_refresh_ahead_refetches_hot_keys_and_backs_off_after_a_failure(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(md._time, "monotonic", lambda: clock[0])
    c = md._TTLCache()
    n = {"ok": 0, "bad": 0}

    def ok():
        n["ok"] += 1
        return n["ok"]

    def bad():
        n["bad"] += 1
        if n["bad"] > 1:
            raise RuntimeError("source down")
        return "first"

    c.get("ok", 10, ok)
    c.get("bad", 10, bad)
    assert c.refresh_ahead() == 0                                      # nothing near expiry yet
    clock[0] += 9.5
    assert c.refresh_ahead() == 1                                      # ok refetched; bad failed
    assert c.get("ok", 10, ok) == 2 and n["bad"] == 2
    clock[0] += 9.5
    assert c.refresh_ahead() == 1 and n["bad"] == 2                    # bad is left alone for BACKOFF s
    clock[0] += 200                                                    # nobody read them: no longer hot
    assert c.refresh_ahead() == 0
