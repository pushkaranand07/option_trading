"""Live option chain from NSE's public API (no broker login needed), shaped for the Plan tab.

Per strike: calls and puts with open interest and its change, last price and its change, volume, implied vol and
the best bid / ask, plus the strike's put-call ratio. NSE reports open interest in contracts; the page shows units
(contracts x lot size), as Indian trading apps do. Summary: spot, ATM, overall PCR, the biggest call / put OI strikes
(resistance / support), max pain. Outside market hours NSE serves the last session's closing book.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

CONTRACT_INFO = "/api/option-chain-contract-info"
CHAIN = "/api/option-chain-v3"
CHART = "/api/chart-databyindex"
NSE_INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
CACHE_SECONDS = 30

_cache: dict[tuple, tuple[float, dict]] = {}
_lock = threading.Lock()


class ChainError(Exception):
    pass


def _client():
    from tradingagents.dataflows.vendors.nse.client import default_client
    return default_client()


def expiries(symbol: str, client=None) -> list[str]:
    info = (client or _client()).get_json(CONTRACT_INFO, {"symbol": symbol}, ttl=600).data
    out = info.get("expiryDates") or []
    if not out:
        raise ChainError(f"NSE lists no option expiries for {symbol} (SENSEX trades on BSE, not NSE).")
    return out


def _leg(o: dict | None, lot: int) -> dict | None:
    if not o:
        return None
    oi, chg = o.get("openInterest") or 0, o.get("changeinOpenInterest") or 0
    return {"oi": oi * lot, "chg_oi": chg * lot, "ltp": o.get("lastPrice") or 0.0, "chg": o.get("change") or 0.0,
            "volume": (o.get("totalTradedVolume") or 0) * lot, "iv": o.get("impliedVolatility") or 0.0,
            "bid": o.get("buyPrice1") or 0.0, "ask": o.get("sellPrice1") or 0.0,
            "bid_qty": o.get("buyQuantity1") or 0, "ask_qty": o.get("sellQuantity1") or 0,      # already in units
            "total_buy_qty": o.get("totalBuyQuantity") or 0, "total_sell_qty": o.get("totalSellQuantity") or 0,
            "id": o.get("identifier")}


def max_pain(rows: list[dict]) -> float | None:
    """The strike at which option writers pay out least at expiry."""
    strikes = [r["strike"] for r in rows]
    if not strikes:
        return None

    def pain(k):
        total = 0.0
        for r in rows:
            if r["ce"]:
                total += max(0.0, k - r["strike"]) * r["ce"]["oi"]
            if r["pe"]:
                total += max(0.0, r["strike"] - k) * r["pe"]["oi"]
        return total
    return min(strikes, key=pain)


def shape(raw: dict, lot: int, strikes_each_side: int = 15) -> dict:
    rec = raw.get("records") or {}
    spot = rec.get("underlyingValue")
    rows = []
    for r in rec.get("data") or []:
        ce, pe = _leg(r.get("CE"), lot), _leg(r.get("PE"), lot)
        if not ce and not pe:
            continue
        pcr = (pe["oi"] / ce["oi"]) if ce and pe and ce["oi"] else None
        rows.append({"strike": float(r["strikePrice"]), "ce": ce, "pe": pe, "pcr": pcr})
    rows.sort(key=lambda r: r["strike"])
    if not rows:
        raise ChainError("NSE returned an empty option chain.")
    all_rows = rows
    atm = min((r["strike"] for r in rows), key=lambda k: abs(k - spot)) if spot else None
    if atm is not None:
        i = [r["strike"] for r in rows].index(atm)
        rows = rows[max(0, i - strikes_each_side): i + strikes_each_side + 1]
    ce_oi = sum(r["ce"]["oi"] for r in all_rows if r["ce"])
    pe_oi = sum(r["pe"]["oi"] for r in all_rows if r["pe"])
    # Walls near the money (the shown strikes): the far-away record OI says little about today's range.
    top_call = max((r for r in rows if r["ce"] and r["strike"] >= (atm or 0)), key=lambda r: r["ce"]["oi"], default=None)
    top_put = max((r for r in rows if r["pe"] and r["strike"] <= (atm or 1e12)), key=lambda r: r["pe"]["oi"], default=None)
    atm_row = next((r for r in rows if r["strike"] == atm), None)
    atm_iv = None
    if atm_row:
        ivs = [x["iv"] for x in (atm_row["ce"], atm_row["pe"]) if x and x["iv"]]
        atm_iv = sum(ivs) / len(ivs) if ivs else None
    return {"spot": spot, "atm": atm, "lot": lot, "timestamp": rec.get("timestamp"), "rows": rows,
            "summary": {"pcr": pe_oi / ce_oi if ce_oi else None, "resistance": top_call["strike"] if top_call else None,
                        "support": top_put["strike"] if top_put else None, "max_pain": max_pain(all_rows),
                        "atm_iv": atm_iv}}


def lot_size(symbol: str) -> int:
    """Current lot: indices from Dhan's scrip master (fallback table), stocks from the NSE store's latest session."""
    from webapp import market_data as md

    if symbol in md.INDICES:
        return int(md.index_lots().get(symbol) or md.INDICES[symbol][4])
    try:
        from datetime import date, timedelta

        from tradingagents.analytics import datastore as ds
        fo = ds.load("fo_summary", symbols=[symbol], start=date.today() - timedelta(days=30))
        if len(fo):
            return int(fo.sort_values("trade_date")["lot_size"].iloc[-1])
    except Exception:
        pass
    raise ChainError(f"Lot size for {symbol} is not known (not in the NSE F&O store).")


def contract(identifier: str, client=None) -> dict:
    """One option's price through the session (NSE ticks, ~10 s apart) with its high, low and previous close.
    ``identifier`` as NSE writes it, e.g. ``OPTIDXNIFTY27-10-2026CE22700.00``. NSE stamps the ticks in IST."""
    if not identifier.startswith(("OPTIDX", "OPTSTK")):
        raise ChainError("Not an NSE option identifier.")
    key = ("contract", identifier)
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    raw = (client or _client()).get_json(CHART, {"index": identifier}, ttl=0).data
    pts = [(int(t) // 1000, float(p)) for t, p in raw.get("grapthData") or [] if p is not None]
    prices = [p for _, p in pts]
    out = {"id": identifier, "points": pts, "prev_close": raw.get("closePrice"),
           "high": max(prices) if prices else None, "low": min(prices) if prices else None,
           "last": prices[-1] if prices else None}
    with _lock:
        _cache[key] = (time.monotonic(), out)
    return out


def chain(symbol: str, expiry: str | None = None, lot: int | None = None, client=None) -> dict:
    """The chain for ``symbol`` (NSE index or F&O stock) and ``expiry`` (default: the nearest), cached 30 s."""
    symbol = symbol.upper()
    client = client or _client()
    exps = expiries(symbol, client)
    expiry = expiry if expiry in exps else exps[0]
    key = (symbol, expiry)
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    kind = "Indices" if symbol in NSE_INDICES else "Equity"
    raw = client.get_json(CHAIN, {"type": kind, "symbol": symbol, "expiry": expiry}, ttl=0).data
    if lot is None:
        lot = lot_size(symbol)
    out = shape(raw, int(lot)) | {"symbol": symbol, "expiry": expiry, "expiries": exps,
                                  "fetched": datetime.now().strftime("%H:%M:%S")}
    with _lock:
        _cache[key] = (time.monotonic(), out)
    return out
