"""Agent-facing renderings of the NSE data, each with its status and provenance.

Every function returns text an LLM can quote, never raises: an outage or a
missing file becomes an explicit "missing — do not estimate" line, and data
that is for a different date than the one asked for says so.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from tradingagents.dataflows.errors import VendorError
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar, now_ist

INDIA_SUFFIXES = (".NS", ".BO")
INDIA_INDICES = frozenset({"^NSEI", "^NSEBANK", "^INDIAVIX", "^CNXIT", "^CNXFIN", "^NSMIDCP", "^BSESN"})


def is_indian_instrument(ticker: str) -> bool:
    upper = (ticker or "").strip().upper()
    return upper.endswith(INDIA_SUFFIXES) or upper in INDIA_INDICES


def _not_applicable(ticker: str, what: str) -> str:
    return f"{what} applies to NSE-listed instruments only; {ticker} is not one. Not applicable."


def _day(text: str) -> date:
    return datetime.strptime(text, "%Y-%m-%d").date()


def fii_dii_text(ticker: str, curr_date: str) -> str:
    from tradingagents.dataflows.vendors.nse.flows import get_fii_dii

    if not is_indian_instrument(ticker):
        return _not_applicable(ticker, "FII/DII flow data")
    try:
        return get_fii_dii(_day(curr_date)).to_text()
    except VendorError as exc:
        return f"FII/DII flows unavailable ({exc}). Treat them as missing; do not estimate."


def fo_contract_text(ticker: str, curr_date: str) -> str:
    from tradingagents.dataflows.vendors.nse.derivatives import (
        LotSizeHistory,
        describe_expiries,
        expiries_from_bhavcopy,
        fno_symbol,
        latest_bhavcopy,
        live_contract_info,
    )

    if not is_indian_instrument(ticker):
        return _not_applicable(ticker, "NSE F&O contract data")
    symbol, day = fno_symbol(ticker), _day(curr_date)
    lines = [f"## NSE F&O contract facts for {symbol} as of {day:%d-%b-%Y}"]
    try:
        bhav = latest_bhavcopy(day)
    except VendorError as exc:
        return f"F&O bhavcopy unavailable ({exc}); lot size and expiries unknown — do not assume them."
    history = LotSizeHistory()
    history.update_from_bhavcopy(bhav)
    history.save()
    if symbol not in set(bhav["symbol"]):
        return f"{symbol} has no F&O contracts in the {bhav['trade_date'].iloc[0]:%d-%b-%Y} bhavcopy (not in F&O)."
    try:
        lot = history.lot_size(symbol, day)
        lines.append(f"Lot size: {lot.lot_size} ({lot.confidence}, from {lot.source} {bhav['trade_date'].iloc[0]:%d-%b-%Y})"
                     + (f" — {lot.note}" if lot.note else ""))
    except VendorError as exc:
        lines.append(f"Lot size unknown: {exc}")
    expiries = [e for e in expiries_from_bhavcopy(bhav, symbol) if e >= day][:6]
    lines.append("Option expiries (from traded contracts; weekdays shift around holidays): "
                 + (describe_expiries(expiries) or "none"))
    if day >= now_ist().date() - timedelta(days=1):
        try:
            live = live_contract_info(symbol)
            lines.append("Live expiries (NSE contract info): " + describe_expiries(live["expiries"][:6]))
        except VendorError:
            pass
    lines.append(f"({bhav.attrs.get('source', 'NSE F&O bhavcopy')})")
    return "\n".join(lines)


def delivery_text(ticker: str, curr_date: str, look_back_days: int = 10) -> str:
    from tradingagents.dataflows.vendors.nse.derivatives import delivery_data, fno_symbol

    if not is_indian_instrument(ticker) or ticker.upper().startswith("^"):
        return _not_applicable(ticker, "Delivery percentage (per-stock)")
    symbol = fno_symbol(ticker)
    calendar = NSECalendar.from_nse()
    end = calendar.latest_session(_day(curr_date))
    sessions = calendar.sessions_between(end - timedelta(days=look_back_days * 2), end)[-look_back_days:]
    rows, missing = [], []
    for day in sessions:
        try:
            df = delivery_data(day)
        except VendorError:
            missing.append(day)
            continue
        hit = df[df["SYMBOL"] == symbol]
        if not hit.empty:
            r = hit.iloc[0]
            rows.append(f"| {day:%d-%b-%Y} | {float(r['CLOSE_PRICE']):,.2f} | {int(r['TTL_TRD_QNTY']):,} | "
                        f"{int(r['DELIV_QTY']):,} | {float(r['DELIV_PER']):.2f}% |")
    if not rows:
        return f"No delivery data found for {symbol} in the {look_back_days} sessions to {end:%d-%b-%Y}."
    out = [f"## Delivery data for {symbol} (NSE sec_bhavdata_full)",
           "| Date | Close | Traded qty | Delivered qty | Delivery % |", "|---|---:|---:|---:|---:|", *rows]
    if missing:
        out.append("Not yet published / unavailable: " + ", ".join(f"{d:%d-%b-%Y}" for d in missing))
    out.append("High delivery % on a rise suggests buying for holding; low delivery % suggests intraday/speculative activity.")
    return "\n".join(out)


def index_health_text(ticker: str, start_date: str, end_date: str) -> str:
    """Whether an index's vendor series can be trusted: volume reliability and missing sessions."""
    from tradingagents.dataflows.vendors.nse.index_volume import (
        constituent_turnover_proxy,
        is_nse_index,
        sanitize_index_ohlcv,
    )
    from tradingagents.dataflows.vendors.nse.indices import ConstituentStore, index_name
    from tradingagents.dataflows.vendors.yahoo.ohlcv import load_ohlcv

    if not is_nse_index(ticker):
        return _not_applicable(ticker, "Index volume/gap check")
    start, end = _day(start_date), _day(end_date)
    try:
        # Unfilled: the default fill carries Volume forward and would hide the problem.
        raw = load_ohlcv(ticker, end.isoformat(), fill_gaps=False)
    except VendorError as exc:
        return f"Index data unavailable ({exc})."
    raw["Date"] = pd.to_datetime(raw["Date"])
    frame = raw[(raw["Date"].dt.date >= start) & (raw["Date"].dt.date <= end)].set_index("Date")
    if frame.empty:
        return f"No {ticker} bars between {start} and {end}."
    calendar = NSECalendar.from_nse()
    proxy = None
    name = index_name(ticker)
    if name in ("NIFTY 50", "NIFTY BANK"):
        try:
            store = ConstituentStore()
            if not store.snapshots.get(name):
                store.refresh(name, now_ist().date())
            proxy = constituent_turnover_proxy(name, start, end, store)
        except VendorError as exc:
            proxy = None
            note = f"(constituent proxy unavailable: {exc})"
        else:
            note = ""
    else:
        note = "(no constituent proxy for this index)"
    result = sanitize_index_ohlcv(frame, name, calendar, proxy)
    text = result.to_text() or "Vendor volume looks consistent and no NSE sessions are missing."
    if proxy is not None:
        recent = result.frame[["Close", "volume_proxy_turnover_cr", "proxy_coverage"]].tail(10)
        text += "\n\nRecent sessions (proxy = ₹ crore traded across constituents):\n" + recent.to_string(
            float_format=lambda v: f"{v:,.2f}")
    return f"## Data health for {ticker} {start:%d-%b-%Y}..{end:%d-%b-%Y}\n{text} {note}".rstrip()
