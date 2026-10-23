"""NSE F&O bhavcopy -> optopsy option-chain schema.

optopsy expects a quote per contract per day with ``bid``, ``ask`` and
``delta``. No free source has historical Indian bid/ask, so this adapter builds
an end-of-day approximation from the bhavcopy and says so:

- ``bid = ask = close`` (the day's last-traded-based close). Pass a spread or
  slippage model to the optopsy strategy to make fills pessimistic.
- ``delta`` from Black-Scholes with the implied volatility solved from that
  close; contracts whose close cannot be inverted (stale or below intrinsic)
  are dropped and counted.
- Untraded contracts (zero contracts) are dropped: their close is a stale
  reference, not a price anyone could trade at.

Every frame it returns carries ``attrs["approximations"]`` listing these.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import pandas as pd

_N = NormalDist()
DEFAULT_RISK_FREE = 0.065      # ~ India 91-day T-bill; pass the period's actual rate for history


def bs_price(spot: float, strike: float, t: float, r: float, vol: float, is_call: bool) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, (spot - strike) if is_call else (strike - spot))
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if is_call:
        return spot * _N.cdf(d1) - strike * math.exp(-r * t) * _N.cdf(d2)
    return strike * math.exp(-r * t) * _N.cdf(-d2) - spot * _N.cdf(-d1)


def bs_delta(spot: float, strike: float, t: float, r: float, vol: float, is_call: bool) -> float:
    d1 = (math.log(spot / strike) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    return _N.cdf(d1) if is_call else _N.cdf(d1) - 1


def implied_vol(price: float, spot: float, strike: float, t: float, r: float, is_call: bool,
                low: float = 0.005, high: float = 5.0, tol: float = 1e-5) -> float | None:
    """Bisection IV; None when ``price`` is outside what any volatility can produce."""
    if t <= 0 or price <= 0:
        return None
    if not bs_price(spot, strike, t, r, low, is_call) <= price <= bs_price(spot, strike, t, r, high, is_call):
        return None
    for _ in range(100):
        mid = (low + high) / 2
        if bs_price(spot, strike, t, r, mid, is_call) > price:
            high = mid
        else:
            low = mid
        if high - low < tol:
            break
    return (low + high) / 2


def bhavcopy_to_optopsy(
    bhav: pd.DataFrame,
    symbol: str,
    underlying: pd.Series | None = None,
    risk_free: float = DEFAULT_RISK_FREE,
) -> pd.DataFrame:
    """One symbol's options from unified bhavcopy rows (``derivatives.fo_bhavcopy``).

    ``underlying`` maps trade date -> spot close; required for legacy-format
    rows, which carry no underlying price.
    """
    opts = bhav[(bhav["symbol"] == symbol) & bhav["option_type"].notna()].copy()
    traded = opts["contracts"].fillna(0) > 0
    dropped_untraded = int((~traded).sum())
    opts = opts[traded]
    if underlying is not None:
        mapped = opts["trade_date"].map(underlying)
        opts["underlying_price"] = mapped.where(mapped.notna(), opts["underlying_price"])
    opts = opts[pd.to_numeric(opts["underlying_price"], errors="coerce") > 0]

    rows, dropped_iv = [], 0
    for rec in opts.itertuples(index=False):
        is_call = rec.option_type == "CE"
        spot, strike, close = float(rec.underlying_price), float(rec.strike), float(rec.close)
        # Expiry at 15:30 IST: count calendar days, at least a part-day on expiry itself.
        t = max((pd.Timestamp(rec.expiry) - pd.Timestamp(rec.trade_date)).days, 0.25) / 365.0
        vol = implied_vol(close, spot, strike, t, risk_free, is_call)
        if vol is None:
            dropped_iv += 1
            continue
        rows.append({
            "underlying_symbol": symbol, "underlying_price": spot,
            "option_type": "call" if is_call else "put",
            "expiration": pd.Timestamp(rec.expiry), "quote_date": pd.Timestamp(rec.trade_date),
            "strike": strike, "bid": close, "ask": close,
            "delta": bs_delta(spot, strike, t, risk_free, vol, is_call),
            "implied_volatility": vol, "volume": float(rec.contracts),
            "open_interest": float(rec.open_interest),
        })
    chain = pd.DataFrame(rows)
    chain.attrs["approximations"] = [
        "end-of-day close used as bid and ask (no historical bid/ask for NSE options)",
        f"delta from Black-Scholes IV solved from close, r={risk_free:.2%}",
        f"{dropped_untraded} untraded contracts dropped",
        f"{dropped_iv} contracts dropped: close not invertible to an implied volatility",
    ]
    return chain
