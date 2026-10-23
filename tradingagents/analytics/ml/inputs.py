"""Model inputs read from the store: market context and NSE derivatives / flow features.

Shared by the Phase 6 scripts so both models see exactly the same, identically
dated inputs. Everything is dated by the close it is known after; ``features.build``
shifts it one session.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from tradingagents.analytics import datastore as ds
from tradingagents.analytics.implied_vol import atm_iv_table
from tradingagents.analytics.ml import derived as md
from tradingagents.analytics.prices import load_prices
from tradingagents.analytics.universe import STOCKS


def market_context() -> tuple[dict[str, pd.Series], pd.Series | None]:
    """NIFTY 20-day return, India VIX and regime probabilities; plus the regime label known
    at each session's start (the label dated the previous close)."""
    p = load_prices(["NIFTY", "INDIAVIX"])
    p = p.assign(trade_date=pd.to_datetime(p["trade_date"])).pivot(index="trade_date", columns="symbol",
                                                                     values="close")
    ctx = {"nifty_ret20": np.log(p["NIFTY"]).diff(20), "vix": np.log(p["INDIAVIX"])}
    regimes = None
    f = ds.store_root() / "regime" / "regime.parquet"
    if f.exists():
        r = pd.read_parquet(f).assign(trade_date=lambda d: pd.to_datetime(d["trade_date"])).set_index("trade_date")
        for col in ("p_calm", "p_choppy", "p_stress"):
            ctx[col] = r[col]
        regimes = r["regime"].shift(1).dropna()
    return ctx, regimes


def store_features(closes: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, pd.Series]]:
    """Per-stock NSE features (OI, PCR, delivery, implied vol) and market-wide positioning
    (FII / Client futures long share)."""
    extra = {}
    extra.update(md.from_fo_summary(ds.load("fo_summary", symbols=STOCKS)))
    extra.update(md.from_delivery(ds.load("delivery", symbols=STOCKS)))
    iv_file = ds.store_root() / "iv" / "iv30.parquet"          # saved by quant_build_store.py
    iv = pd.read_parquet(iv_file) if iv_file.exists() else atm_iv_table(ds.load("option_chain", symbols=STOCKS))
    extra.update(md.from_iv(iv[iv["symbol"].isin(STOCKS)], closes))
    return extra, md.from_participant(ds.load("participant"))
