"""Results-day iron butterfly on stock options (spec: docs/strategies/results_iron_fly.md).

Sell the at-the-money straddle at the close before a company's board meeting on
results, buy wings one straddle-price away, and close everything at the close of
the first session after the meeting. The legs are priced from the same prepared
option chain as ``condor.py`` (close, or NSE settlement when a leg did not trade),
with the same fills, charges and spread-width cap.

Results dates come from NSE's board-meeting API; an event is used only if its
intimation reached NSE before the entry session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from tradingagents.analytics.backfill import raw_root
from tradingagents.analytics.condor import SIGN, TYPE, _fill, _prepare, close_cost
from tradingagents.analytics.costs import (
    DEFAULT_RATES,
    DEFAULT_SLIPPAGE,
    OPTIONS,
    ChargeRates,
    Slippage,
    fill_charges,
)
from tradingagents.analytics.implied_vol import expiry_atm
from tradingagents.integrations.optopsy.adapter import DEFAULT_RISK_FREE

LEGS = ("long_put", "short_put", "short_call", "long_call")
BOARD_MEETINGS = "/api/corporate-board-meetings"


# ---------------------------------------------------------------- events

def fetch_board_meetings(symbol: str, client=None, root: Path | None = None, start: date = date(2018, 1, 1),
                         end: date | None = None, refresh: bool = False) -> list[dict]:
    """NSE board meetings for ``symbol`` (cached as raw JSON next to the other NSE files)."""
    path = (root or raw_root()) / "board_meetings" / f"{symbol}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    if client is None:
        from tradingagents.dataflows.vendors.nse.client import default_client
        client = default_client()
    end = end or date.today()
    rows = client.get_json(BOARD_MEETINGS, {"index": "equities", "symbol": symbol,
                                            "from_date": f"{start:%d-%m-%Y}", "to_date": f"{end:%d-%m-%Y}"},
                           ttl=0).data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def is_results(row: dict) -> bool:
    purpose = (row.get("bm_purpose") or "").lower()
    desc = (row.get("bm_desc") or "").lower()
    return "result" in purpose or ("intimation" in purpose and "financial result" in desc)


def results_events(rows: list[dict]) -> pd.DataFrame:
    """One row per results date: ``date`` and ``announced`` (earliest intimation seen)."""
    out = {}
    for row in rows:
        if not is_results(row):
            continue
        d = datetime.strptime(row["bm_date"], "%d-%b-%Y").date()
        stamp = row.get("bm_timestamp") or ""
        try:
            announced = datetime.strptime(stamp, "%d-%b-%Y %H:%M:%S")
        except ValueError:
            announced = None
        prev = out.get(d)
        if prev is None or (announced is not None and (prev is pd.NaT or announced < prev)):
            out[d] = announced if announced is not None else pd.NaT
    df = pd.DataFrame({"date": list(out), "announced": list(out.values())})
    return df.sort_values("date").reset_index(drop=True)


# ---------------------------------------------------------------- trades

@dataclass(frozen=True)
class FlyParams:
    wing_mult: float = 1.0          # wings at least this many straddle prices beyond the short strike
    max_dte: int = 45
    risk_free: float = DEFAULT_RISK_FREE


DEFAULT_FLY = FlyParams()


@dataclass
class FlyTrade:
    symbol: str
    event_date: date | None
    entry_date: date
    exit_date: date
    expiry: date
    strikes: dict[str, float]
    lot: int
    credit: float                   # per unit, after slippage
    max_risk: float                 # per unit: widest wing - credit
    entry_prices: dict[str, float] = field(default_factory=dict)
    exit_prices: dict[str, float] = field(default_factory=dict)
    charges: float = 0.0
    pnl: float = 0.0
    flags: list[str] = field(default_factory=list)

    @property
    def return_on_risk(self) -> float:
        return self.pnl / (self.max_risk * self.lot) if self.max_risk > 0 else float("nan")


def build_fly(day_chain: pd.DataFrame, params: FlyParams = DEFAULT_FLY):
    """Strikes and entry marks for one (day, expiry); None if it can't be built."""
    atm = expiry_atm(day_chain, params.risk_free, min_contracts=1)
    if atm is None:
        return None
    k = atm["atm_strike"]
    listed = day_chain.set_index(["option_type", "strike"]).sort_index()
    shorts = {}
    for leg in ("short_put", "short_call"):
        row = listed.loc[(TYPE[leg], k)]
        row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        if not (row["contracts"] > 0 and row["close"] > 0):
            return None
        shorts[leg] = float(row["close"])
    width = params.wing_mult * (shorts["short_put"] + shorts["short_call"])
    puts = sorted(listed.loc["PE"].index)
    calls = sorted(listed.loc["CE"].index)
    lp = [s for s in puts if s <= k - width]
    lc = [s for s in calls if s >= k + width]
    if not lp or not lc:
        return None
    strikes = {"long_put": lp[-1], "short_put": k, "short_call": k, "long_call": lc[0]}
    prices, flags = dict(shorts), []
    for leg in ("long_put", "long_call"):
        row = listed.loc[(TYPE[leg], strikes[leg])]
        row = row.iloc[0] if isinstance(row, pd.DataFrame) else row
        traded = row["contracts"] > 0 and row["close"] > 0
        prices[leg] = float(row["close"]) if traded else float(row["settle"]) if row["settle"] > 0 else float("nan")
        if not traded:
            flags.append(f"{leg} untraded at entry, settlement price used")
    if any(not np.isfinite(p) for p in prices.values()):
        return None
    return strikes, prices, flags


def window_trade(prep: dict, symbol: str, lot: float, entry: date, exit_: date, event_date: date | None = None,
                 params: FlyParams = DEFAULT_FLY, rates: ChargeRates = DEFAULT_RATES,
                 slippage: Slippage = DEFAULT_SLIPPAGE) -> FlyTrade | None:
    """Open the fly at ``entry``'s close and close it at ``exit_``'s close."""
    g = prep["by_day"].get(entry)
    if g is None or not np.isfinite(lot):
        return None
    candidates = sorted(e for e in set(g["expiry"]) & prep["monthly"]
                        if e > exit_ and (e - entry).days <= params.max_dte)
    if not candidates:
        return None
    expiry = candidates[0]
    built = build_fly(g[g["expiry"] == expiry], params)
    if built is None:
        return None
    strikes, prices, flags = built
    fills = {leg: _fill(p, buying=SIGN[leg] > 0, slip=slippage) for leg, p in prices.items()}
    credit = sum(-SIGN[leg] * fills[leg] for leg in LEGS)
    width = max(strikes["short_put"] - strikes["long_put"], strikes["long_call"] - strikes["short_call"])
    if credit <= 0 or width <= credit:
        return None
    lot = int(lot)
    charges = sum(fill_charges(OPTIONS, lot, fills[leg], "buy" if SIGN[leg] > 0 else "sell", rates) for leg in LEGS)
    marks = {}
    for leg, k in strikes.items():
        v = prep["marks"].get((exit_, expiry, TYPE[leg], k))
        if v is None or not np.isfinite(v):
            return None                      # can't be priced on the exit day: no trade recorded
        marks[leg] = v
    trade = FlyTrade(symbol, event_date, entry, exit_, expiry, strikes, lot, credit, width - credit,
                     entry_prices=fills, flags=list(flags))
    for leg in LEGS:
        fill = _fill(marks[leg], buying=SIGN[leg] < 0, slip=slippage)
        charges += fill_charges(OPTIONS, lot, fill, "buy" if SIGN[leg] < 0 else "sell", rates)
        trade.exit_prices[leg] = fill
    debit, capped = close_cost(trade.exit_prices, strikes)
    if capped:
        trade.flags.append("exit marks implied a spread wider than its strikes; capped")
    trade.charges = charges
    trade.pnl = (credit - debit) * lot - charges
    return trade


def event_windows(days: list[date], events: pd.DataFrame) -> list[tuple[date, date, date]]:
    """(event date, entry session, exit session) for events announced before their entry."""
    out = []
    idx = pd.Index(days)
    for d, announced in zip(events["date"], events["announced"], strict=True):
        i = idx.searchsorted(d)                  # first session on or after d
        if i == 0 or i >= len(days):
            continue
        entry = days[i - 1]
        j = i + 1 if days[i] == d else i         # first session strictly after d
        if j >= len(days):
            continue
        if pd.isna(announced) or announced.date() >= entry:
            continue
        out.append((d, entry, days[j]))
    return out


def event_trades(chain: pd.DataFrame, lots: pd.Series, events: pd.DataFrame, symbol: str,
                 params: FlyParams = DEFAULT_FLY, rates: ChargeRates = DEFAULT_RATES,
                 slippage: Slippage = DEFAULT_SLIPPAGE) -> list[FlyTrade]:
    prep = _prepare(chain)
    lot_of = lots.copy()
    lot_of.index = pd.to_datetime(lot_of.index).date
    trades = []
    for d, entry, exit_ in event_windows(prep["days"], events):
        t = window_trade(prep, symbol, lot_of.get(entry, np.nan), entry, exit_, d, params, rates, slippage)
        if t is not None:
            trades.append(t)
    return trades


def quiet_entries(days: list[date], event_dates: list[date], buffer: int = 5) -> list[int]:
    """Session positions with no results date within ``buffer`` sessions either side."""
    idx = pd.Index(days)
    blocked = set()
    for d in event_dates:
        i = idx.searchsorted(d)
        blocked.update(range(i - buffer, i + buffer + 1))
    return [i for i in range(len(days)) if i not in blocked]
