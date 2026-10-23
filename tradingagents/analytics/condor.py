"""Short iron condor on monthly index options, end-of-day (plan, Phase 3).

Rules (agreed with the user, 2026-10-23):

- One condor at a time per underlying, on the nearest **monthly** expiry with
  ``min_dte``..``max_dte`` calendar days left.
- Entry on a session whose signal is on. The signal for session *t* may use
  only data published before *t*; the fill is *t*'s close, less slippage.
- Short put / short call: the out-of-the-money strikes whose Black-76 delta
  (own IV, parity forward) is nearest ``short_delta``. Wings: the nearest
  listed strikes at least ``wing_pct`` of the forward further out.
- Every session the position is marked at each leg's close, or NSE's
  settlement price when the leg did not trade.
- Exit when profit reaches ``take_profit`` x credit or loss reaches
  ``stop_loss`` x credit. A manual trader sees this only after the close, so
  the exit fills at the **next** session's close.
- Otherwise held to expiry and settled at intrinsic value against the index
  close; in-the-money long legs pay STT on exercise.
- Every order pays Dhan brokerage and statutory charges (``costs.py``) and
  slippage (``Slippage``). Results are in rupees per lot and as a fraction of
  the trade's maximum risk, so lot-size changes do not distort them.

Known approximations: end-of-day closes, not bid/ask; a close may be the
last trade of the day rather than the final quote. Wings use the settlement
price when they did not trade on the entry day, and are flagged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from statistics import NormalDist

import numpy as np
import pandas as pd

from tradingagents.analytics.costs import (
    DEFAULT_RATES,
    DEFAULT_SLIPPAGE,
    OPTIONS,
    ChargeRates,
    Slippage,
    fill_charges,
)
from tradingagents.analytics.implied_vol import black76_iv, expiry_atm
from tradingagents.integrations.optopsy.adapter import DEFAULT_RISK_FREE

_N = NormalDist()
LEGS = ("long_put", "short_put", "short_call", "long_call")
SIGN = {"long_put": 1, "short_put": -1, "short_call": -1, "long_call": 1}   # +1 bought, -1 sold
TYPE = {"long_put": "PE", "short_put": "PE", "short_call": "CE", "long_call": "CE"}


@dataclass(frozen=True)
class CondorParams:
    short_delta: float = 0.20
    wing_pct: float = 0.03
    take_profit: float = 0.50
    stop_loss: float = 2.00
    min_dte: int = 20
    max_dte: int = 45
    risk_free: float = DEFAULT_RISK_FREE


DEFAULT_PARAMS = CondorParams()


@dataclass
class CondorTrade:
    entry_date: date
    expiry: date
    strikes: dict[str, float]
    entry_prices: dict[str, float]
    lot: int
    credit: float                       # per unit, after entry slippage
    max_risk: float                     # per unit: widest wing - credit
    exit_date: date | None = None
    exit_prices: dict[str, float] = field(default_factory=dict)
    exit_reason: str = ""
    charges: float = 0.0                # rupees, whole trade
    pnl: float = 0.0                    # rupees, whole trade, after charges
    flags: list[str] = field(default_factory=list)
    # This trade's share of the daily series (date -> return on max risk); sums to return_on_risk.
    daily: dict = field(default_factory=dict)

    @property
    def return_on_risk(self) -> float:
        return self.pnl / (self.max_risk * self.lot) if self.max_risk > 0 else float("nan")


def monthly_expiries(chain: pd.DataFrame) -> set:
    """The last listed expiry of each calendar month."""
    exp = pd.Series(sorted(set(chain["expiry"])))
    return set(exp.groupby(exp.map(lambda d: (d.year, d.month))).max())


def black76_delta(forward: float, strike: float, t: float, r: float, vol: float, is_call: bool) -> float:
    d1 = (math.log(forward / strike) + vol * vol * t / 2) / (vol * math.sqrt(t))
    disc = math.exp(-r * t)
    return disc * _N.cdf(d1) if is_call else -disc * _N.cdf(-d1)


def _price(row: pd.Series) -> float:
    """A leg's mark: its close if it traded, else NSE's settlement price."""
    if row["contracts"] > 0 and row["close"] > 0:
        return float(row["close"])
    return float(row["settle"]) if row["settle"] > 0 else float("nan")


def choose_strikes(day_chain: pd.DataFrame, params: CondorParams) -> tuple[dict, dict, list[str]] | None:
    """Strikes and entry closes for one expiry on one day; None if the condor can't be built."""
    atm = expiry_atm(day_chain, params.risk_free, min_contracts=1)
    if atm is None:
        return None
    f, t = atm["forward"], atm["days"] / 365.0
    traded = day_chain[(day_chain["contracts"] > 0) & (day_chain["close"] > 0)]
    best = {}
    for leg, is_call in (("short_put", False), ("short_call", True)):
        side = traded[(traded["option_type"] == ("CE" if is_call else "PE"))
                      & ((traded["strike"] > f) if is_call else (traded["strike"] < f))]
        scored = []
        for _, row in side.iterrows():
            vol = black76_iv(row["close"], f, row["strike"], t, params.risk_free, is_call)
            if vol:
                scored.append((abs(abs(black76_delta(f, row["strike"], t, params.risk_free, vol, is_call))
                                   - params.short_delta), row["strike"]))
        if not scored:
            return None
        best[leg] = min(scored)[1]
    listed = day_chain.set_index(["option_type", "strike"]).sort_index()
    put_strikes = sorted(listed.loc["PE"].index) if "PE" in listed.index.get_level_values(0) else []
    call_strikes = sorted(listed.loc["CE"].index) if "CE" in listed.index.get_level_values(0) else []
    lp = [k for k in put_strikes if k <= best["short_put"] - params.wing_pct * f]
    lc = [k for k in call_strikes if k >= best["short_call"] + params.wing_pct * f]
    if not lp or not lc:
        return None
    strikes = {"long_put": lp[-1], "short_put": best["short_put"], "short_call": best["short_call"],
               "long_call": lc[0]}
    prices, flags = {}, []
    for leg, k in strikes.items():
        row = listed.loc[(TYPE[leg], k)]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        prices[leg] = _price(row)
        if not (row["contracts"] > 0):
            flags.append(f"{leg} untraded at entry, settlement price used")
    if any(not np.isfinite(p) for p in prices.values()):
        return None
    return strikes, prices, flags


def close_cost(marks: dict, strikes: dict) -> tuple[float, bool]:
    """Per-unit cost to buy back the condor, each spread capped at its width.

    A put or call spread can never cost more than its width to close (at worst it
    expires there), but end-of-day marks are not simultaneous: an untraded wing at
    NSE's settlement price next to a short leg's last trade can imply more. The
    cap removes that artefact; ``True`` says it was needed.
    """
    put_w = strikes["short_put"] - strikes["long_put"]
    call_w = strikes["long_call"] - strikes["short_call"]
    put = marks["short_put"] - marks["long_put"]
    call = marks["short_call"] - marks["long_call"]
    capped_put, capped_call = min(max(put, 0.0), put_w), min(max(call, 0.0), call_w)
    return capped_put + capped_call, (capped_put != put or capped_call != call)


def _fill(price: float, buying: bool, slip: Slippage) -> float:
    s = slip.option_ticks * slip.option_tick_size + slip.option_premium_pct * price
    return price + s if buying else max(price - s, 0.0)


# Prepared chains, keyed by the caller's object: a walk-forward runs dozens of simulations
# on the same chain, and re-indexing it each time dominated the run time. The entry holds
# the chain itself, so a recycled id() can never match a different frame.
_PREPARED: dict[int, tuple[pd.DataFrame, dict]] = {}


def _prepare(chain: pd.DataFrame) -> dict:
    hit = _PREPARED.get(id(chain))
    if hit is not None and hit[0] is chain:
        return hit[1]
    c = chain.copy()
    c["trade_date"] = pd.to_datetime(c["trade_date"]).dt.date
    c["expiry"] = pd.to_datetime(c["expiry"]).dt.date
    traded = (c["contracts"] > 0) & (c["close"] > 0)
    price = np.where(traded, c["close"], np.where(c["settle"] > 0, c["settle"], np.nan))
    keys = zip(c["trade_date"], c["expiry"], c["option_type"], c["strike"], strict=True)
    prepared = {
        "monthly": monthly_expiries(c),
        "by_day": dict(iter(c.groupby("trade_date"))),
        "marks": dict(zip(keys, price.astype(float), strict=True)),
        "strikes": {},                       # memo of choose_strikes per (day, expiry, params)
    }
    prepared["days"] = sorted(prepared["by_day"])
    if len(_PREPARED) > 8:                   # a handful of underlyings at a time is plenty
        _PREPARED.clear()
    _PREPARED[id(chain)] = (chain, prepared)
    return prepared


def simulate(
    chain: pd.DataFrame,
    spot: pd.Series,
    lots: pd.Series,
    signal: pd.Series,
    params: CondorParams = DEFAULT_PARAMS,
    rates: ChargeRates = DEFAULT_RATES,
    slippage: Slippage = DEFAULT_SLIPPAGE,
) -> tuple[list[CondorTrade], pd.Series]:
    """Trades, and daily mark-to-market P&L as a fraction of the open trade's max risk.

    ``chain``: one underlying's option chain (store schema). ``spot``: index close
    by date (expiry settlement). ``lots``: lot size by date. ``signal``: bool by
    date, already lagged (True on *t* means "enter during *t*").
    """
    prep = _prepare(chain)
    monthly, by_day, days, marks_of = prep["monthly"], prep["by_day"], prep["days"], prep["marks"]
    spot = spot.copy()
    spot.index = pd.to_datetime(spot.index).date
    spot_items = sorted(spot.items())
    sig = signal.copy()
    sig.index = pd.to_datetime(sig.index).date
    lots_by_day = lots.copy()
    lots_by_day.index = pd.to_datetime(lots_by_day.index).date

    trades: list[CondorTrade] = []
    daily = pd.Series(0.0, index=pd.to_datetime(pd.Index(days)))
    open_trade: CondorTrade | None = None
    last_value = 0.0              # mark-to-market P&L per unit of the open trade, previous session
    exit_tomorrow = ""

    def leg_marks(day: date, trade: CondorTrade) -> dict | None:
        marks = {}
        for leg, k in trade.strikes.items():
            v = marks_of.get((day, trade.expiry, TYPE[leg], k))
            if v is None or not np.isfinite(v):
                return None
            marks[leg] = v
        return marks

    def close_out(day: date, trade: CondorTrade, prices: dict, reason: str, at_expiry: bool) -> None:
        trade.exit_date, trade.exit_reason = day, reason
        charges = trade.charges
        for leg in LEGS:
            p = prices[leg]
            if at_expiry:
                fill = p
                if SIGN[leg] > 0 and p > 0:     # long leg exercised in the money
                    charges += rates.stt_options_exercise * p * trade.lot
            else:
                fill = _fill(p, buying=SIGN[leg] < 0, slip=slippage)
                charges += fill_charges(OPTIONS, trade.lot, fill, "buy" if SIGN[leg] < 0 else "sell", rates)
            trade.exit_prices[leg] = fill
        # Cost to buy back the shorts minus the longs' proceeds, each spread capped at its width.
        debit, capped = close_cost(trade.exit_prices, trade.strikes)
        if capped:
            trade.flags.append(f"{day}: exit marks implied a spread wider than its strikes; capped")
        trade.charges = charges
        trade.pnl = (trade.credit - debit) * trade.lot - charges

    for i, day in enumerate(days):
        if open_trade is not None:
            t = open_trade
            if day >= t.expiry:
                s = spot.get(t.expiry, np.nan)
                if not np.isfinite(s):
                    # No index close for the expiry day: settle against the last close
                    # before it (never the entry prices, which would erase the outcome).
                    earlier = [v for d, v in spot_items if d <= t.expiry and np.isfinite(v)]
                    s = earlier[-1] if earlier else np.nan
                    t.flags.append("no index close on expiry; settled on the last earlier close")
                if np.isfinite(s):
                    intrinsic = {leg: max(0.0, (s - k) if TYPE[leg] == "CE" else (k - s))
                                 for leg, k in t.strikes.items()}
                    close_out(day, t, intrinsic, "expiry", at_expiry=True)
                else:
                    t.flags.append("no index close at all before expiry; closed at the day's marks")
                    close_out(day, t, leg_marks(day, t) or t.entry_prices, "expiry", at_expiry=False)
            else:
                marks = leg_marks(day, t)
                if marks is None:
                    t.flags.append(f"{day}: a leg missing, mark carried")
                elif exit_tomorrow:
                    close_out(day, t, marks, exit_tomorrow, at_expiry=False)
                else:
                    # Premium P&L per unit decides the exits; the daily series also
                    # carries the entry charges (t.charges holds only those until exit).
                    value = t.credit - close_cost(marks, t.strikes)[0]
                    if value >= params.take_profit * t.credit:
                        exit_tomorrow = "take_profit"
                    elif -value >= params.stop_loss * t.credit:
                        exit_tomorrow = "stop_loss"
                    net = value - t.charges / t.lot
                    daily.iloc[i] = (net - last_value) / t.max_risk
                    last_value = net
            if t.exit_date is not None:
                final_per_unit = (t.pnl / t.lot)
                daily.iloc[i] += (final_per_unit - last_value) / t.max_risk
            t.daily[daily.index[i]] = float(daily.iloc[i])
            if t.exit_date is not None:
                trades.append(t)
                open_trade, last_value, exit_tomorrow = None, 0.0, ""
            continue

        if not bool(sig.get(day, False)):
            continue
        g = by_day[day]
        candidates = sorted(e for e in set(g["expiry"]) & monthly
                            if params.min_dte <= (e - day).days <= params.max_dte)
        lot = lots_by_day.get(day, np.nan)
        if not candidates or not np.isfinite(lot):
            continue
        expiry = candidates[0]
        key = (day, expiry, params.short_delta, params.wing_pct, params.risk_free)
        if key not in prep["strikes"]:
            prep["strikes"][key] = choose_strikes(g[g["expiry"] == expiry], params)
        built = prep["strikes"][key]
        if built is None:
            continue
        strikes, prices, flags = built
        fills = {leg: _fill(p, buying=SIGN[leg] > 0, slip=slippage) for leg, p in prices.items()}
        credit = sum(-SIGN[leg] * fills[leg] for leg in LEGS)
        width = max(strikes["short_put"] - strikes["long_put"], strikes["long_call"] - strikes["short_call"])
        if credit <= 0 or width <= credit:
            continue
        lot = int(lot)
        charges = sum(fill_charges(OPTIONS, lot, fills[leg], "buy" if SIGN[leg] > 0 else "sell", rates)
                      for leg in LEGS)
        open_trade = CondorTrade(day, expiry, strikes, fills, lot, credit, width - credit,
                                 charges=charges, flags=list(flags))
        # Entry charges hit the day of entry.
        daily.iloc[i] = -charges / lot / open_trade.max_risk
        open_trade.daily[daily.index[i]] = float(daily.iloc[i])
        last_value = -charges / lot

    return trades, daily


def summarize(trades: list[CondorTrade]) -> dict:
    if not trades:
        return {"trades": 0}
    r = np.array([t.return_on_risk for t in trades])
    pnl = np.array([t.pnl for t in trades])
    reasons = pd.Series([t.exit_reason for t in trades]).value_counts().to_dict()
    return {"trades": len(trades), "hit_rate": float((pnl > 0).mean()),
            "avg_return_on_risk": float(r.mean()), "median_return_on_risk": float(np.median(r)),
            "worst_return_on_risk": float(r.min()), "total_pnl_per_lot_basis": float(pnl.sum()),
            "exit_reasons": reasons, "flagged": sum(bool(t.flags) for t in trades)}


def simulate_staggered(
    chain: pd.DataFrame,
    spot: pd.Series,
    lots: pd.Series,
    signal: pd.Series,
    params: CondorParams = DEFAULT_PARAMS,
    books: int = 4,
    **kwargs,
) -> tuple[list[CondorTrade], pd.Series]:
    """``books`` staggered condor books: book *j* may enter only in ISO weeks with
    ``week % books == j``, so together they enter about weekly, each still holding at
    most one condor. Capital is split equally: each book's daily P&L counts 1/books
    (also inside each trade's ``daily``), while ``return_on_risk`` stays per trade.
    """
    if books <= 1:
        return simulate(chain, spot, lots, signal, params, **kwargs)
    idx = pd.to_datetime(signal.index)
    weeks = np.asarray(idx.isocalendar().week, dtype=int)
    trades, total = [], None
    for j in range(books):
        book_signal = signal & pd.Series(weeks % books == j, index=signal.index)
        book_trades, daily = simulate(chain, spot, lots, book_signal, params, **kwargs)
        for t in book_trades:
            t.daily = {d: v / books for d, v in t.daily.items()}
        trades += book_trades
        total = daily / books if total is None else total.add(daily / books, fill_value=0.0)
    trades.sort(key=lambda t: t.entry_date)
    return trades, total
