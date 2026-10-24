"""Daily snapshot of NSE option bid/ask quotes, to measure trading costs instead of assuming them.

NSE's end-of-day bhavcopy has closes but no quotes, so every backtest assumes a
slippage (``costs.Slippage``: 1 tick + 1% of premium per leg per fill). NSE's
option-chain API does show the best bid and offer per strike; after the close it
holds the closing book. Captured every evening, it gives measured half-spreads by
stock, strike and day (including results eves) to check that assumption against.

Raw JSON is kept exactly as served, under
``<data_cache_dir>/quant/raw/option_quotes/<snapshot date>/<symbol>_<expiry>.json``.
The snapshot date comes from NSE's own timestamp, so a run on a holiday or weekend
(when NSE still serves the last session's book) writes nothing new.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from tradingagents.analytics.backfill import raw_root
from tradingagents.analytics.costs import DEFAULT_SLIPPAGE, Slippage

logger = logging.getLogger(__name__)

INDICES = ("NIFTY", "BANKNIFTY")
CONTRACT_INFO = "/api/option-chain-contract-info"
CHAIN = "/api/option-chain-v3"


def quotes_root(root: Path | None = None) -> Path:
    return (root or raw_root()) / "option_quotes"


def snapshot_date(raw: dict) -> date | None:
    stamp = (raw.get("records") or {}).get("timestamp")
    try:
        return datetime.strptime(stamp, "%d-%b-%Y %H:%M:%S").date()
    except (TypeError, ValueError):
        return None


def capture(symbols, client=None, root: Path | None = None, expiries: int = 3) -> dict:
    """Save the current chain of the first ``expiries`` expiries for each symbol.
    Returns counts: ``saved``, ``already`` (this snapshot was saved before), ``failed``."""
    if client is None:
        from tradingagents.dataflows.vendors.nse.client import default_client
        client = default_client()
    base = quotes_root(root)
    counts = {"saved": 0, "already": 0, "failed": 0}
    for symbol in symbols:
        kind = "Indices" if symbol in INDICES else "Equity"
        try:
            info = client.get_json(CONTRACT_INFO, {"symbol": symbol}, ttl=0).data
            for expiry in (info.get("expiryDates") or [])[:expiries]:
                raw = client.get_json(CHAIN, {"type": kind, "symbol": symbol, "expiry": expiry}, ttl=0).data
                day = snapshot_date(raw)
                if day is None or not (raw.get("records") or {}).get("data"):
                    counts["failed"] += 1
                    continue
                exp = datetime.strptime(expiry, "%d-%b-%Y").date()
                path = base / f"{day:%Y-%m-%d}" / f"{symbol}_{exp:%Y-%m-%d}.json"
                if path.exists():
                    counts["already"] += 1
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(raw), encoding="utf-8")
                tmp.replace(path)
                counts["saved"] += 1
        except Exception as exc:                 # one symbol failing must not lose the others
            logger.warning("option quotes for %s failed: %s", symbol, exc)
            counts["failed"] += 1
    return counts


def parse(raw: dict, symbol: str) -> pd.DataFrame:
    """One row per (strike, type) with both a bid and an ask."""
    rec = raw.get("records") or {}
    day = snapshot_date(raw)
    rows = []
    for r in rec.get("data") or []:
        for typ in ("CE", "PE"):
            o = r.get(typ) or {}
            bid, ask = o.get("buyPrice1") or 0, o.get("sellPrice1") or 0
            if bid <= 0 or ask <= 0 or ask < bid:
                continue
            rows.append({
                "trade_date": day, "symbol": symbol,
                "expiry": datetime.strptime(o["expiryDate"], "%d-%m-%Y").date(),
                "strike": float(r["strikePrice"]), "option_type": typ,
                "bid": float(bid), "ask": float(ask), "bid_qty": o.get("buyQuantity1"), "ask_qty": o.get("sellQuantity1"),
                "last": o.get("lastPrice"), "iv": o.get("impliedVolatility"), "volume": o.get("totalTradedVolume"),
                "open_interest": o.get("openInterest"), "underlying": o.get("underlyingValue", rec.get("underlyingValue")),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["mid"] = (df["bid"] + df["ask"]) / 2
        df["half_spread"] = (df["ask"] - df["bid"]) / 2
    return df


def load(root: Path | None = None) -> pd.DataFrame:
    frames = []
    for path in sorted(quotes_root(root).glob("*/*.json")):
        symbol = path.stem.rsplit("_", 1)[0]
        frames.append(parse(json.loads(path.read_text(encoding="utf-8")), symbol))
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def versus_model(quotes: pd.DataFrame, slippage: Slippage = DEFAULT_SLIPPAGE, band: float = 0.10) -> pd.DataFrame:
    """Median real half-spread / modelled slippage per (day, symbol), for strikes within
    ``band`` of the underlying (where option strategies actually trade)."""
    q = quotes[(quotes["strike"] / quotes["underlying"] - 1).abs() <= band].copy()
    q["model"] = slippage.option_ticks * slippage.option_tick_size + slippage.option_premium_pct * q["mid"]
    q["ratio"] = q["half_spread"] / q["model"]
    return q.groupby(["trade_date", "symbol"]).agg(strikes=("ratio", "size"), real_vs_model=("ratio", "median"),
                                                   half_spread=("half_spread", "median")).reset_index()
