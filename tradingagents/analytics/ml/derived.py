"""Derivatives, delivery and flow features from the NSE store (plan, Phase 6).

Each function returns wide frames (date x symbol) or market-wide series, dated
by ``trade_date``: the session the NSE file describes, published after its
close. ``features.build`` shifts every input one session, so the row for
session *t* sees files for *t-1* and earlier: exactly the ``known_from`` rule.

These are ready-made frames, which ``features.leak_check`` cannot recompute;
the dating rule above is what keeps them honest, and the tests pin it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _wide(df: pd.DataFrame, value: str) -> pd.DataFrame:
    d = df.assign(trade_date=pd.to_datetime(df["trade_date"]))
    return d.pivot_table(index="trade_date", columns="symbol", values=value, aggfunc="last").sort_index()


def from_fo_summary(fo: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Futures open-interest change and option positioning per stock."""
    oi = _wide(fo, "fut_oi")
    out = {
        "fut_oi_chg1": oi.pct_change(fill_method=None),
        "fut_oi_chg5": oi.pct_change(5, fill_method=None),
        "pcr_oi": _wide(fo, "pcr_oi"),
        "pcr_volume": _wide(fo, "pcr_volume"),
    }
    opt = _wide(fo, "opt_turnover")
    out["opt_activity"] = np.log(opt / opt.rolling(20).mean())
    return out


def from_delivery(delivery: pd.DataFrame) -> dict[str, pd.DataFrame]:
    pct = _wide(delivery, "deliv_pct")
    return {"deliv_pct": pct, "deliv_vs20": pct - pct.rolling(20).mean()}


def from_participant(participant: pd.DataFrame) -> dict[str, pd.Series]:
    """Market-wide positioning: net-long share of FII and Client in index and stock futures."""
    p = participant.assign(trade_date=pd.to_datetime(participant["trade_date"])).set_index("trade_date")
    out = {}
    for who in ("FII", "Client"):
        g = p[p["category"] == who].sort_index()
        for kind in ("idx", "stk"):
            long_, short = g[f"fut_{kind}_long"].astype(float), g[f"fut_{kind}_short"].astype(float)
            ratio = long_ / (long_ + short)
            name = f"{who.lower()}_fut_{kind}_long_share"
            out[name] = ratio
            out[f"{name}_chg5"] = ratio.diff(5)
    return out


def from_iv(iv_table: pd.DataFrame, closes: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Each stock's 30-day implied vol and its premium over 20-session realised vol."""
    iv30 = _wide(iv_table, "iv30")
    rv20 = np.log(closes).diff().rolling(20).std() * np.sqrt(252)
    return {"iv30": iv30, "iv_minus_rv20": iv30 - rv20.reindex(index=iv30.index, columns=iv30.columns)}
