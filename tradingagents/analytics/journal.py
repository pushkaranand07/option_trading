"""Trade journal: what actually makes or loses money in the user's own Dhan trades.

Reads a broker tradebook (CSV or Excel; column names are matched loosely, since
report formats differ), pairs buys and sells into round trips first-in-first-out
per contract, and breaks the results down by holding period (intraday, up to a
week, up to a month, longer), instrument, buying vs selling, time of entry, day
of week and, when the file has one, the user's own reason/tag column.

Charges: taken from the file when it has a charges column, otherwise estimated
with the Dhan + statutory model in ``costs.py`` (equity is charged as intraday when
opened and closed the same day, delivery otherwise).

The tradebook is personal data: keep it under ``reports/journal/`` (gitignored).
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.analytics.costs import DELIVERY, FUTURES, INTRADAY, OPTIONS, fill_charges

INDEX_NAMES = ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "NIFTY", "SENSEX", "BANKEX")

# Canonical field -> header names seen in broker reports (compared lower-case, spaces/punctuation removed).
ALIASES = {
    "date": ["tradedatetime", "datetime", "tradedate", "date", "orderdate", "transactiondate"],
    "time": ["tradetime", "exchangetime", "executiontime", "orderexecutiontime", "ordertime", "time"],
    "symbol": ["tradingsymbol", "symbol", "scrip", "scripname", "instrument", "security", "securityname",
               "contract", "name", "customsymbol"],
    "side": ["buysell", "transactiontype", "tradetype", "side", "bs", "type"],
    "qty": ["quantity", "qty", "tradedqty", "filledqty", "tradedquantity", "filledquantity", "tradeqty"],
    "price": ["tradeprice", "price", "tradedprice", "avgprice", "averageprice", "rate", "executedprice",
              "tradeavgprice"],
    "charges": ["charges", "totalcharges", "brokerageandcharges", "totaltaxes"],
    "reason": ["reason", "tag", "tags", "remarks", "remark", "note", "notes", "setup", "strategy"],
}

HORIZONS = ("intraday", "up to 1 week", "1-4 weeks", "over a month")


def _key(name) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _find_header(raw: pd.DataFrame) -> int:
    """Row index of the header: the first row naming a symbol, a quantity and a price column."""
    for i in range(min(len(raw), 30)):
        keys = {_key(v) for v in raw.iloc[i].tolist()}
        if all(any(a in keys for a in ALIASES[f]) for f in ("symbol", "qty", "price")):
            return i
    raise ValueError("No header row with symbol, quantity and price columns found in the first 30 rows")


def read_tradebook(path: Path) -> pd.DataFrame:
    """One row per executed trade: datetime, symbol, side (+1 buy / -1 sell), qty, price, charges, reason."""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        raw = pd.read_excel(path, header=None, dtype=object)
    else:
        # Title lines above the table have fewer fields than the table: pad every row to the widest.
        with path.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.reader(handle))
        width = max((len(r) for r in rows), default=0)
        raw = pd.DataFrame([r + [None] * (width - len(r)) for r in rows], dtype=object)
        raw = raw.replace("", None)
    h = _find_header(raw)
    df = raw.iloc[h + 1:].copy()
    df.columns = [_key(c) for c in raw.iloc[h]]
    df = df.dropna(how="all")
    out, missing = {}, []
    for field, names in ALIASES.items():
        col = next((n for n in names if n in df.columns), None)
        if col is None:
            if field not in ("charges", "reason", "date", "time"):
                missing.append(field)
        else:
            out[field] = df[col]
    if "date" not in out and "time" not in out:
        missing.append("date")
    if missing:
        raise ValueError(f"Could not find columns for {missing}; the file has: {list(df.columns)}")
    # A time column that already carries the date is used alone; otherwise date (+ time).
    time_has_date = "time" in out and out["time"].astype(str).str.contains(r"[-/]").all()
    if time_has_date or "date" not in out:
        stamp = out["time"].astype(str)
    elif "time" in out and out["date"].name != out["time"].name:
        stamp = out["date"].astype(str).str.split().str[0] + " " + out["time"].astype(str)
    else:
        stamp = out["date"].astype(str)
    t = pd.DataFrame({k: v for k, v in out.items() if k not in ("date", "time")})
    t["datetime"] = pd.to_datetime(stamp, dayfirst=True, errors="coerce", format="mixed")
    side = t["side"].astype(str).str.strip().str.upper().str[0]
    t["side"] = side.map({"B": 1, "S": -1})
    t["qty"] = pd.to_numeric(t["qty"].astype(str).str.replace(",", ""), errors="coerce").abs()
    t["price"] = pd.to_numeric(t["price"].astype(str).str.replace(",", ""), errors="coerce")
    if "charges" in t:
        t["charges"] = pd.to_numeric(t["charges"].astype(str).str.replace(",", ""), errors="coerce")
    t["symbol"] = t["symbol"].astype(str).str.strip().str.upper()
    bad = t[["datetime", "side", "qty", "price"]].isna().any(axis=1)
    if bad.any():
        raise ValueError(f"{int(bad.sum())} rows could not be read (date, buy/sell, quantity or price); "
                         f"first: {t[bad].head(3).to_dict('records')}")
    # Reports often list the newest trade first; with date-only stamps the file order is the only
    # order within a day, so put the file in time order before the (stable) sort.
    if t["datetime"].iloc[0] > t["datetime"].iloc[-1]:
        t = t.iloc[::-1]
    return t.sort_values("datetime", kind="stable").reset_index(drop=True)


@dataclass(frozen=True)
class Instrument:
    kind: str            # "option" | "future" | "equity"
    underlying: str
    index: bool
    option_type: str | None


def classify(symbol: str) -> Instrument:
    s = re.sub(r"[- ](EQ|BE)$", "", symbol.upper().strip()).replace("-", " ")
    compact = s.replace(" ", "")
    under = next((n for n in INDEX_NAMES if compact.startswith(n)), None)
    if under is None:
        alpha = re.match(r"[A-Z&]+", compact)
        under = alpha.group(0) if alpha else compact
        # "RELIANCEOCTFUT" -> "RELIANCE"; option symbols already stop at the first digit.
        under = re.sub(r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)?FUT$", "", under) or under
    opt = re.search(r"\d(CE|PE|CALL|PUT)$", compact)         # a strike always precedes CE/PE ("RELIANCE" ends in CE)
    if opt:
        return Instrument("option", under, under in INDEX_NAMES, "CE" if opt.group(1) in ("CE", "CALL") else "PE")
    if re.search(r"FUT", compact):
        return Instrument("future", under, under in INDEX_NAMES, None)
    return Instrument("equity", under, False, None)


@dataclass
class RoundTrip:
    symbol: str
    kind: str
    underlying: str
    index: bool
    direction: int        # +1 opened by buying, -1 opened by selling
    open_time: pd.Timestamp
    close_time: pd.Timestamp
    qty: float
    entry: float
    exit: float
    charges: float
    reason: str = ""

    @property
    def gross(self) -> float:
        return (self.exit - self.entry) * self.qty * self.direction

    @property
    def net(self) -> float:
        return self.gross - self.charges

    @property
    def horizon(self) -> str:
        days = (self.close_time.normalize() - self.open_time.normalize()).days
        if days == 0:
            return HORIZONS[0]
        return HORIZONS[1] if days <= 7 else HORIZONS[2] if days <= 31 else HORIZONS[3]

    @property
    def style(self) -> str:
        if self.kind == "option":
            return "option buying" if self.direction > 0 else "option selling"
        if self.kind == "future":
            return "futures long" if self.direction > 0 else "futures short"
        return "shares long" if self.direction > 0 else "shares short"


def _segment(kind: str, same_day: bool) -> str:
    return OPTIONS if kind == "option" else FUTURES if kind == "future" else INTRADAY if same_day else DELIVERY


def round_trips(trades: pd.DataFrame) -> tuple[list[RoundTrip], pd.DataFrame]:
    """FIFO-matched round trips, and the positions still open at the end of the file."""
    lots: dict[str, deque] = defaultdict(deque)       # symbol -> [sign, qty, price, time, charge/unit, reason]
    trips: list[RoundTrip] = []
    has_charges = "charges" in trades and trades["charges"].notna().any()
    for row in trades.itertuples(index=False):
        inst = classify(row.symbol)
        sign, qty, price = int(row.side), float(row.qty), float(row.price)
        per_unit = (float(row.charges) / qty) if has_charges and pd.notna(row.charges) and qty else None
        reason = str(getattr(row, "reason", "") or "")
        reason = "" if reason.lower() == "nan" else reason
        book = lots[row.symbol]
        while qty > 0 and book and book[0][0] != sign:
            o_sign, o_qty, o_price, o_time, o_cpu, o_reason = book[0]
            m = min(qty, o_qty)
            same_day = o_time.normalize() == row.datetime.normalize()
            if has_charges:
                charges = (o_cpu or 0.0) * m + (per_unit or 0.0) * m
            else:
                seg = _segment(inst.kind, same_day)
                charges = (fill_charges(seg, m, o_price, "buy" if o_sign > 0 else "sell")
                           + fill_charges(seg, m, price, "buy" if sign > 0 else "sell"))
            trips.append(RoundTrip(row.symbol, inst.kind, inst.underlying, inst.index, o_sign, o_time, row.datetime,
                                   m, o_price, price, charges, o_reason or reason))
            qty -= m
            if m == o_qty:
                book.popleft()
            else:
                book[0][1] = o_qty - m
        if qty > 0:
            book.append([sign, qty, price, row.datetime, per_unit, reason])
    still_open = pd.DataFrame([{"symbol": s, "direction": "long" if b[0] > 0 else "short", "qty": b[1],
                                "price": b[2], "opened": b[3]} for s, q in lots.items() for b in q])
    return trips, still_open


def summarize(trips: list[RoundTrip], by: str | None = None) -> pd.DataFrame:
    """Trades, win rate, average win / loss, net per trade, total, charges as a share of gross profit."""
    if not trips:
        return pd.DataFrame()
    df = pd.DataFrame({"group": [getattr(t, by) if by else "all" for t in trips],
                       "net": [t.net for t in trips], "gross": [t.gross for t in trips],
                       "charges": [t.charges for t in trips]})

    def stats(g: pd.DataFrame) -> pd.Series:
        wins, losses = g.net[g.net > 0], g.net[g.net <= 0]
        gross_profit = g.gross[g.gross > 0].sum()
        return pd.Series({
            "trades": len(g), "win_rate": (g.net > 0).mean(),
            "avg_win": wins.mean() if len(wins) else 0.0, "avg_loss": losses.mean() if len(losses) else 0.0,
            "net_per_trade": g.net.mean(), "total_net": g.net.sum(), "charges": g.charges.sum(),
            "charges_share_of_gross_profit": g.charges.sum() / gross_profit if gross_profit > 0 else np.nan,
            "profit_factor": wins.sum() / -losses.sum() if losses.sum() < 0 else np.inf,
        })

    out = df.groupby("group", sort=False).apply(stats, include_groups=False)
    return out.sort_values("total_net", ascending=False)


def filter_horizon(trips: list[RoundTrip], horizon: str) -> list[RoundTrip]:
    return trips if horizon == "all" else [t for t in trips if t.horizon == horizon]
