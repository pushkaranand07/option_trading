"""Daily OHLCV for the research universe from Yahoo Finance (plan, Phase 1).

Yahoo's ``close`` is adjusted for splits and bonuses (not dividends);
``adj_close`` is also adjusted for dividends and is what return calculations
use. Neither is the price that traded on the day: option strikes must be
compared with NSE's own prices (``underlying_price`` / ``fut_close`` in the
``fo_summary`` dataset), never with these.

Like the NSE datasets, a bar's ``known_from`` is the next session: a signal
built on day *t*'s close can only be acted on from *t+1*.

Repairs, each marked in the ``source`` column:

- :func:`merge_nse_indices` replaces Yahoo's NIFTY / BANKNIFTY / India VIX bars
  with NSE's official daily values (``nse``); Yahoo stays only where NSE has none.
- :func:`fill_stock_gaps` fills sessions Yahoo lacks for a stock from NSE's
  equity bhavcopy (``nse_fill``): NSE's day-over-day move is applied to Yahoo's
  adjusted previous bar, so the filled bar is on Yahoo's adjusted basis.

:func:`quality_report` then lists what is still missing or suspicious, so gaps
are seen, not silently forward-filled.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from tradingagents.analytics.datastore import (
    add_known_from,
    next_sessions,
    store_root,
    write_parquet,
)
from tradingagents.analytics.universe import HISTORY_START, YAHOO_TICKERS

INDEX_SYMBOLS = ("NIFTY", "BANKNIFTY", "INDIAVIX")
PRICE_COLUMNS = ["trade_date", "symbol", "open", "high", "low", "close", "adj_close", "volume",
                 "dividend", "split", "source"]
JUMP_THRESHOLD = 0.20   # a one-day move this large with no split recorded is flagged


def _history(ticker: str, start: date, end: date) -> pd.DataFrame:
    from tradingagents.dataflows.vendors.yahoo.market import get_daily_history

    return get_daily_history(ticker, start.isoformat(), (end + timedelta(days=1)).isoformat())


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
    df["source"] = "yahoo"
    return df.dropna(subset=["close"]).drop_duplicates("trade_date", keep="last").reset_index(drop=True)


def fetch_prices(
    symbols: Iterable[str] | None = None,
    start: date = HISTORY_START,
    end: date | None = None,
    history: Callable[[str, date, date], pd.DataFrame] = _history,
) -> pd.DataFrame:
    # Yesterday by default: today's bar may be a live, unfinished session.
    end = end or date.today() - timedelta(days=1)
    symbols = list(symbols) if symbols is not None else list(YAHOO_TICKERS)
    frames = [normalize_history(history(YAHOO_TICKERS[s], start, end), s) for s in symbols]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=PRICE_COLUMNS)


def merge_nse_indices(prices: pd.DataFrame, index_close: pd.DataFrame) -> pd.DataFrame:
    """NSE's official index bars replace Yahoo's wherever NSE has the day."""
    nse = index_close[index_close["symbol"].isin(INDEX_SYMBOLS)].dropna(subset=["close"])
    if nse.empty:
        return prices
    nse = pd.DataFrame({
        "trade_date": nse["trade_date"].to_numpy(), "symbol": nse["symbol"].to_numpy(),
        "open": nse["open"].to_numpy(float), "high": nse["high"].to_numpy(float),
        "low": nse["low"].to_numpy(float), "close": nse["close"].to_numpy(float),
        "adj_close": nse["close"].to_numpy(float), "volume": nse["volume"].to_numpy(float),
        "dividend": 0.0, "split": 0.0, "source": "nse",
    })
    keys = set(zip(nse["trade_date"], nse["symbol"], strict=True))
    keep = [(d, s) not in keys for d, s in zip(prices["trade_date"], prices["symbol"], strict=True)]
    return (pd.concat([prices[keep], nse], ignore_index=True)
            .sort_values(["symbol", "trade_date"]).reset_index(drop=True))


def fill_stock_gaps(
    prices: pd.DataFrame,
    trading_days: Iterable[date],
    fetch_day: Callable[[date], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Fill NSE sessions Yahoo lacks, per stock, from NSE's unadjusted bhavcopy.

    For a missing day *d* after Yahoo's bar on *p*: every NSE price on *d* is
    scaled by ``yahoo_close(p) / nse_close(p)``, which puts it on Yahoo's split
    basis, and ``adj_close`` keeps *p*'s dividend ratio. Runs of missing days are
    filled in order, each from the one before.
    """
    if fetch_day is None:
        from tradingagents.dataflows.vendors.nse.derivatives import equity_bhavcopy as fetch_day
    days = sorted(set(trading_days))
    cache: dict[date, pd.DataFrame | None] = {}

    def nse(d: date) -> pd.DataFrame | None:
        if d not in cache:
            try:
                cache[d] = fetch_day(d).drop_duplicates("symbol").set_index("symbol")
            except Exception:       # a day NSE cannot serve stays a gap, and the report shows it
                cache[d] = None
        return cache[d]

    stocks = [s for s in prices["symbol"].unique() if s not in INDEX_SYMBOLS]
    added = []
    for symbol in stocks:
        g = prices[prices["symbol"] == symbol].set_index("trade_date").sort_index()
        have = dict(g.to_dict("index"))
        first, last = g.index[0], g.index[-1]
        for i, d in enumerate(days):
            if d in have or not (first < d <= last) or i == 0:
                continue
            prev = days[i - 1]
            base = have.get(prev)
            today, before = nse(d), nse(prev)
            if base is None or today is None or before is None                     or symbol not in today.index or symbol not in before.index:
                continue
            scale = base["close"] / float(before.loc[symbol, "close"])
            row = today.loc[symbol]
            close = float(row["close"]) * scale
            bar = {"open": float(row["open"]) * scale, "high": float(row["high"]) * scale,
                   "low": float(row["low"]) * scale, "close": close,
                   "adj_close": close * base["adj_close"] / base["close"],
                   "volume": float(row["volume"]), "dividend": 0.0, "split": 0.0, "source": "nse_fill"}
            have[d] = bar
            added.append({"trade_date": d, "symbol": symbol, **bar})
    if not added:
        return prices
    return (pd.concat([prices, pd.DataFrame(added)], ignore_index=True)
            .sort_values(["symbol", "trade_date"]).reset_index(drop=True))


def prices_path(root: Path | None = None) -> Path:
    return (root or store_root()) / "prices" / "prices.parquet"


def save_prices(prices: pd.DataFrame, trading_days: Iterable[date], root: Path | None = None) -> Path:
    """Stamp ``known_from`` from NSE's trading calendar and write the Parquet file."""
    days = set(trading_days) | set(prices["trade_date"])
    df = add_known_from(prices, next_sessions(days))
    return write_parquet(df, prices_path(root))


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
        for d, m, s in zip(g["trade_date"], move, g["split"], strict=True):
            if pd.notna(m) and abs(m) > JUMP_THRESHOLD and not s:
                issues.append({"symbol": symbol, "trade_date": d, "issue": "jump_no_split", "value": float(m)})
    return pd.DataFrame(issues, columns=["symbol", "trade_date", "issue", "value"])
