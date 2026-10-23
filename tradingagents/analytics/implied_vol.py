"""At-the-money implied volatility from the stored option chain (plan, Phase 3).

Method, the same idea as India VIX:

1. For each expiry, the forward is taken from put-call parity at the strike
   where call and put closes are nearest: ``F = K + e^(rT) (C - P)``. No
   futures price or dividend estimate is needed.
2. ATM IV is the mean of the call and put implied vols (Black-76 on ``F``) at
   the traded strike nearest ``F``.
3. A constant 30-calendar-day IV interpolates total variance (sigma^2 T)
   between the expiries either side of 30 days, matching the 21-session GARCH
   horizon.

Only contracts that traded at least ``min_contracts`` that day are used: an
untraded contract's close is a stale reference, not a price.

Like the chain it comes from, a value dated *d* is known from the next session.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from tradingagents.integrations.optopsy.adapter import DEFAULT_RISK_FREE, implied_vol

TARGET_DAYS = 30
MIN_DAYS = 3          # expiries closer than this are dominated by expiry-day noise
MIN_CONTRACTS = 10


def black76_iv(price: float, forward: float, strike: float, t: float, r: float, is_call: bool) -> float | None:
    """Black-76 IV through the Black-Scholes solver: Black-76 equals Black-Scholes on spot ``F e^(-rT)``."""
    return implied_vol(price, forward * math.exp(-r * t), strike, t, r, is_call)


def expiry_atm(chain: pd.DataFrame, r: float = DEFAULT_RISK_FREE, min_contracts: int = MIN_CONTRACTS) -> dict | None:
    """ATM forward and IV for one (day, symbol, expiry) slice of the chain."""
    traded = chain[chain["contracts"] >= min_contracts]
    calls = traded[traded["option_type"] == "CE"].set_index("strike")["close"]
    puts = traded[traded["option_type"] == "PE"].set_index("strike")["close"]
    both = pd.concat({"c": calls, "p": puts}, axis=1).dropna()
    both = both[(both["c"] > 0) & (both["p"] > 0)]
    if both.empty:
        return None
    day, expiry = chain["trade_date"].iloc[0], chain["expiry"].iloc[0]
    days = (pd.Timestamp(expiry) - pd.Timestamp(day)).days
    t = days / 365.0
    k_parity = (both["c"] - both["p"]).abs().idxmin()
    forward = k_parity + math.exp(r * t) * (both.loc[k_parity, "c"] - both.loc[k_parity, "p"])
    k_atm = min(both.index, key=lambda k: abs(k - forward))
    ivs = [black76_iv(both.loc[k_atm, "c"], forward, k_atm, t, r, True),
           black76_iv(both.loc[k_atm, "p"], forward, k_atm, t, r, False)]
    ivs = [v for v in ivs if v is not None]
    if not ivs:
        return None
    return {"expiry": expiry, "days": days, "forward": forward, "atm_strike": k_atm, "atm_iv": float(np.mean(ivs))}


def constant_maturity(points: pd.DataFrame, target_days: int = TARGET_DAYS) -> float:
    """Interpolate total variance to ``target_days``; nearest expiry if none bracket it."""
    pts = points.sort_values("days")
    below, above = pts[pts["days"] <= target_days], pts[pts["days"] >= target_days]
    if len(below) and len(above):
        a, b = below.iloc[-1], above.iloc[0]
        if a["days"] == b["days"]:
            return float(a["atm_iv"])
        w = (b["days"] - target_days) / (b["days"] - a["days"])
        total_var = w * a["atm_iv"] ** 2 * a["days"] + (1 - w) * b["atm_iv"] ** 2 * b["days"]
        return float(math.sqrt(total_var / target_days))
    nearest = pts.iloc[(pts["days"] - target_days).abs().argmin()]
    return float(nearest["atm_iv"])


def atm_iv_table(chain: pd.DataFrame, r: float = DEFAULT_RISK_FREE, min_contracts: int = MIN_CONTRACTS,
                 target_days: int = TARGET_DAYS) -> pd.DataFrame:
    """One row per (trade_date, symbol): near-expiry ATM IV and the 30-day constant-maturity IV."""
    rows = []
    for (day, symbol), g in chain.groupby(["trade_date", "symbol"], sort=True):
        points = []
        for _, e in g.groupby("expiry"):
            if (pd.Timestamp(e["expiry"].iloc[0]) - pd.Timestamp(day)).days < MIN_DAYS:
                continue
            atm = expiry_atm(e, r, min_contracts)
            if atm:
                points.append(atm)
        if not points:
            continue
        pts = pd.DataFrame(points)
        near = pts.sort_values("days").iloc[0]
        rows.append({"trade_date": day, "symbol": symbol, "near_expiry": near["expiry"], "near_days": near["days"],
                     "near_iv": near["atm_iv"], "forward": near["forward"],
                     "iv30": constant_maturity(pts, target_days), "expiries_used": len(pts)})
    out = pd.DataFrame(rows)
    if "known_from" in chain and len(out):
        known = chain.drop_duplicates(["trade_date"]).set_index("trade_date")["known_from"]
        out["known_from"] = out["trade_date"].map(known)
    return out
