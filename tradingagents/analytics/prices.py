"""Daily OHLCV for the research universe from Yahoo Finance (plan, Phase 1).

Yahoo's ``close`` is adjusted for splits and bonuses (not dividends);
``adj_close`` is also adjusted for dividends and is what return calculations
use. Neither is the price that traded on the day: option strikes must be
compared with NSE's own prices (``underlying_price`` / ``fut_close`` in the
``fo_summary`` dataset), never with these.

Like the NSE datasets, a bar's ``known_from`` is the next session: a signal
built on day *t*'s close can only be acted on from *t+1*.

:func:`quality_report` compares Yahoo with NSE's trading calendar and flags
missing sessions and unexplained one-day jumps, so gaps are seen, not silently
forward-filled.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.analytics.datastore import add_known_from, next_sessions, store_root
from tradingagents.analytics.universe import HISTORY_START, YAHOO_TICKERS

PRICE_COLUMNS = ["trade_date", "symbol", "open", "high", "low", "close", "adj_close", "volume",
                 "dividend", "split"]
JUMP_THRESHOLD = 0.20   # a one-day move this large with no split recorded is flagged


def _history(ticker: str, start: date, end: date) -> pd.DataFrame:
    import yfinance as yf

    from tradingagents.dataflows.vendors.yahoo.common import yf_retry

    return yf_retry(lambda: yf.Ticker(ticker).history(
        start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=False, actions=True))


def normalize_history(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    idx = pd.to_datetime(raw.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df = pd.DataFrame({
        "trade_date": idx.normalize().date,
        "symbol": symbol,
        "open": raw["Open"].to_numpy(dtype=float),
        "high": raw["High"].to_numpy(dtype=float),
        "low": raw["Low"].to_numpy(dtype=float),
        "close": raw["Close"].to_numpy(dtype=float),
        "adj_close": raw["Adj Close"].to_numpy(dtype=float),
        "volume": raw["Volume"].to_numpy(dtype=float),
        "dividend": raw.get("Dividends", pd.Series(0.0, index=raw.index)).to_numpy(dtype=float),
        "split": raw.get("Stock Splits", pd.Series(0.0, index=raw.index)).to_numpy(dtype=float),
    })
    return df.dropna(subset=["close"]).drop_duplicates("trade_date", keep="last").reset_index(drop=True)


def fetch_prices(
    symbols: Iterable[str] | None = None,
    start: date = HISTORY_START,
    end: date | None = None,
    history: Callable[[str, date, date], pd.DataFrame] = _history,
) -> pd.DataFrame:
    end = end or date.today()
    symbols = list(symbols) if symbols is not None else list(YAHOO_TICKERS)
    frames = [normalize_history(history(YAHOO_TICKERS[s], start, end), s) for s in symbols]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def prices_path(root: Path | None = None) -> Path:
    return (root or store_root()) / "prices" / "prices.parquet"


def save_prices(prices: pd.DataFrame, trading_days: Iterable[date], root: Path | None = None) -> Path:
    """Stamp ``known_from`` from NSE's trading calendar and write the Parquet file."""
    days = set(trading_days) | set(prices["trade_date"])
    df = add_known_from(prices, next_sessions(days))
    path = prices_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def load_prices(symbols: Iterable[str] | None = None, root: Path | None = None) -> pd.DataFrame:
    df = pd.read_parquet(prices_path(root))
    if symbols is not None:
        df = df[df["symbol"].isin(set(symbols))]
    return df.reset_index(drop=True)


def quality_report(prices: pd.DataFrame, trading_days: Iterable[date]) -> pd.DataFrame:
    """One row per problem: NSE sessions Yahoo lacks, and big jumps with no split recorded."""
    days = sorted(set(trading_days))
    issues = []
    for symbol, g in prices.groupby("symbol"):
        g = g.sort_values("trade_date")
        have = set(g["trade_date"])
        first, last = g["trade_date"].iloc[0], g["trade_date"].iloc[-1]
        for d in days:
            if first <= d <= last and d not in have:
                issues.append({"symbol": symbol, "trade_date": d, "issue": "missing_session", "value": None})
        move = g["adj_close"].pct_change()
        for d, m, s in zip(g["trade_date"], move, g["split"]):
            if pd.notna(m) and abs(m) > JUMP_THRESHOLD and not s:
                issues.append({"symbol": symbol, "trade_date": d, "issue": "jump_no_split", "value": float(m)})
    return pd.DataFrame(issues, columns=["symbol", "trade_date", "issue", "value"])
