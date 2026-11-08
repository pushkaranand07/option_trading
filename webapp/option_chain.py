"""Live option chain from NSE's public API (no broker login needed), shaped for the Plan tab.

Per strike: calls and puts with open interest and its change, last price and its change, volume, implied vol and
the best bid / ask, plus the strike's put-call ratio. NSE reports open interest in contracts; the page shows units
(contracts x lot size), as Indian trading apps do. Summary: spot, ATM, overall PCR, the biggest call / put OI strikes
(resistance / support), max pain. Outside market hours NSE serves the last session's closing book.
"""

from __future__ import annotations

import logging
from datetime import datetime

from webapp import market_data as md, timeutil

logger = logging.getLogger(__name__)

CONTRACT_INFO = "/api/option-chain-contract-info"
CHAIN = "/api/option-chain-v3"
CHART = "/api/chart-databyindex"
NSE_INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
CACHE_SECONDS = 10            # NSE itself updates about every 45 s; don't add much on top


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


def valid_expiries(symbol: str) -> list[str]:
    """The option expiries that can be asked for, in NSE's spelling (``17-Nov-2026``): NSE's list; with Dhan enabled
    its ``/optionchain/expirylist`` (cached for the day) is a cross-check, and the list when NSE has none. Never
    raises: ``[]`` when neither source has one."""
    symbol = symbol.upper()
    try:
        nse = expiries(symbol)
    except Exception:
        nse = []
    dhan = []
    if md.dhan.enabled and symbol in md.INDICES:
        try:
            raw = md._cache.get(("dhan expiries day", symbol, timeutil.today_ist().isoformat()), 86400,
                                lambda: md.expiries(symbol))
            dhan = [datetime.strptime(x, "%Y-%m-%d").strftime("%d-%b-%Y") for x in raw or []]
        except Exception:
            dhan = []
    if nse and dhan and set(dhan) - set(nse):
        logger.warning("expiries of %s differ: NSE %s, Dhan %s", symbol, nse, dhan)
    return list(nse or dhan)


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
        from datetime import timedelta

        from tradingagents.analytics import datastore as ds
        fo = ds.load("fo_summary", symbols=[symbol], start=timeutil.today_ist() - timedelta(days=30))
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
    return md._cache.get(("nse contract", identifier), CACHE_SECONDS, lambda: _contract(identifier, client))


def _contract(identifier: str, client) -> dict:
    raw = (client or _client()).get_json(CHART, {"index": identifier}, ttl=0).data
    pts = [(int(t) // 1000, float(p)) for t, p in raw.get("grapthData") or [] if p is not None]
    prices = [p for _, p in pts]
    return {"id": identifier, "points": pts, "prev_close": raw.get("closePrice"),
            "high": max(prices) if prices else None, "low": min(prices) if prices else None,
            "last": prices[-1] if prices else None}


def _pick_expiry(expiry: str | None, exps: list[str], strict: bool) -> str:
    """``expiry`` when NSE lists it; otherwise the nearest, or (``strict``) a ChainError for a named unknown expiry."""
    if strict and expiry and expiry not in exps:
        raise ChainError(f"unknown expiry {expiry}; valid: {', '.join(exps)}")
    return expiry if expiry in exps else exps[0]


def chain(symbol: str, expiry: str | None = None, lot: int | None = None, client=None, *, strict: bool = False) -> dict:
    """The chain for ``symbol`` (NSE index or F&O stock) and ``expiry`` (default: the nearest), cached 10 s.
    An expiry NSE doesn't list gets the nearest one, unless ``strict``: then it raises ChainError."""
    symbol = symbol.upper()
    client = client or _client()
    exps = expiries(symbol, client)
    expiry = _pick_expiry(expiry, exps, strict)
    return md._cache.get(("nse chain", symbol, expiry), CACHE_SECONDS, lambda: _chain(symbol, expiry, exps, lot, client))


def full_chain(symbol: str, expiry: str | None = None, lot: int | None = None, client=None, *,
               strict: bool = False) -> dict:
    """Every strike of the chain (no display window), for pricing legs already held: a leg can drift far from the
    money. Same NSE fetch as ``chain`` (cached together); ``strict`` as there."""
    symbol = symbol.upper()
    client = client or _client()
    exps = expiries(symbol, client)
    expiry = _pick_expiry(expiry, exps, strict)
    return md._cache.get(("nse chain full", symbol, expiry), CACHE_SECONDS, lambda: _chain(symbol, expiry, exps, lot, client, 10 ** 6))


def _raw_chain(symbol: str, expiry: str, client) -> dict:
    kind = "Indices" if symbol in NSE_INDICES else "Equity"
    return md._cache.get(("nse chain raw", symbol, expiry), CACHE_SECONDS,
                         lambda: client.get_json(CHAIN, {"type": kind, "symbol": symbol, "expiry": expiry}, ttl=0).data)


def _chain(symbol: str, expiry: str, exps: list[str], lot: int | None, client, strikes_each_side: int = 15) -> dict:
    raw = _raw_chain(symbol, expiry, client)
    if lot is None:
        lot = lot_size(symbol)
    return shape(raw, int(lot), strikes_each_side) | {"symbol": symbol, "expiry": expiry, "expiries": exps,
                                                      "fetched": timeutil.now_ist().strftime("%H:%M:%S")}
