"""The fixed research universe for the quant signal layer (plan, Phase 0).

Chosen on 2026-10-23: the stocks in the top ~40 by F&O futures turnover (week to
22-Oct-2026) that were also in F&O on 02-Jan-2018 and 03-Jan-2022, so all have
the full history. Dropped for that reason: BSE, ETERNAL, JIOFIN, LTM, DIXON,
PERSISTENT, LAURUSLABS, INDHOTEL, INDUSTOWER, ADANIENSOL (listed in F&O after
2018), YESBANK and ADANIPOWER (left F&O in between), IDEA (penny stock, repeated
dilution).

This list is today's survivors, so results from it lean optimistic; every report
built on it must carry :data:`SURVIVORSHIP_NOTE`.
"""

from __future__ import annotations

from datetime import date

HISTORY_START = date(2018, 1, 1)

INDICES = ("NIFTY", "BANKNIFTY")

STOCKS_BY_SECTOR: dict[str, tuple[str, ...]] = {
    "banks_finance": ("HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "BAJFINANCE",
                      "FEDERALBNK", "CANBK", "PNB"),
    "it": ("INFY", "TCS", "HCLTECH", "TECHM", "WIPRO"),
    "energy_conglomerate": ("RELIANCE", "ADANIENT"),
    "telecom": ("BHARTIARTL",),
    "metals": ("TATASTEEL", "HINDALCO", "JSWSTEEL"),
    "auto": ("M&M", "MARUTI"),
    "pharma": ("SUNPHARMA", "DIVISLAB"),
    "fmcg": ("ITC", "NESTLEIND"),
    "infra_capital_goods": ("LT", "BHEL"),
    "aviation": ("INDIGO",),
}

STOCKS: tuple[str, ...] = tuple(s for group in STOCKS_BY_SECTOR.values() for s in group)

SECTOR_OF: dict[str, str] = {s: sector for sector, group in STOCKS_BY_SECTOR.items() for s in group}

SYMBOLS: tuple[str, ...] = INDICES + STOCKS

# Yahoo Finance tickers for daily OHLCV.
YAHOO_TICKERS: dict[str, str] = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIAVIX": "^INDIAVIX",
                                 **{s: f"{s}.NS" for s in STOCKS}}

SURVIVORSHIP_NOTE = (
    "Survivorship: the stock universe is today's liquid F&O names that were also listed in 2018. "
    "Stocks that fell out of F&O or collapsed are not in it, so historical results lean optimistic."
)
