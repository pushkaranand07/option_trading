"""Rule-based setups: intraday (5-minute), BTST (daily) and an option-chain read.

The same per-bar rules drive the live signal and the backtest in planner.py, so
the win rates the page shows are the record of exactly the rule it applies now.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss.replace(0, 1e-9))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def r2(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 2)


def now_ist() -> datetime:
    return datetime.now(IST)


def market_open(at: datetime | None = None) -> bool:
    at = at or now_ist()
    return at.weekday() < 5 and time(9, 15) <= at.time() <= time(15, 30)


# ---------- intraday ----------

def daily_trend(daily: pd.DataFrame) -> pd.Series:
    """+1 uptrend, -1 downtrend, 0 sideways per day, from the 20/50-day averages."""
    c = daily["close"]
    e20, e50 = ema(c, 20), ema(c, 50)
    t = np.where((c > e50) & (e20 > e50), 1, np.where((c < e50) & (e20 < e50), -1, 0))
    return pd.Series(t, index=pd.Index(daily.index.date))


def intraday_frame(bars: pd.DataFrame, daily: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-bar indicators, the four bull and four bear conditions, and the resulting side.

    A side needs all four conditions, and with ``daily`` the bigger trend as of the
    previous close must point the same way: across 14 NSE names, the looser
    three-of-four rule against the trend lost the most after costs.
    """
    df = bars.copy()
    day = df.index.date
    c = df["close"]
    tp = (df["high"] + df["low"] + c) / 3
    cum_v = df["volume"].groupby(day).cumsum()
    vwap_vol = (tp * df["volume"]).groupby(day).cumsum() / cum_v.replace(0, np.nan)
    # Indices trade no volume of their own; fall back to the session's average typical price.
    vwap_tp = tp.groupby(day).cumsum() / (tp.groupby(day).cumcount() + 1)
    df["vwap"] = vwap_vol.where(cum_v > 0, vwap_tp)
    df["day_open"] = df["open"].groupby(day).transform("first")
    df["ema9"], df["ema21"] = ema(c, 9), ema(c, 21)
    df["rsi"] = rsi(c)
    df["atr"] = atr(df)
    df["bull"] = ((c > df["vwap"]).astype(int) + (df["ema9"] > df["ema21"]) + df["rsi"].between(50, 70)
                  + (c > df["day_open"]))
    df["bear"] = ((c < df["vwap"]).astype(int) + (df["ema9"] < df["ema21"]) + df["rsi"].between(30, 50)
                  + (c < df["day_open"]))
    if daily is not None:
        trend = daily_trend(daily)
        # Known at the previous session's close: no peeking at the day being traded.
        prev = pd.Series(trend.to_numpy(), index=trend.index).shift(1)
        df["trend"] = pd.Series(day, index=df.index).map(prev).fillna(0).to_numpy()
    else:
        df["trend"] = 0
    up_ok = df["trend"] >= 0 if daily is None else df["trend"] == 1
    down_ok = df["trend"] <= 0 if daily is None else df["trend"] == -1
    df["side"] = np.where((df["bull"] == 4) & up_ok, "BUY", np.where((df["bear"] == 4) & down_ok, "SELL", "WAIT"))
    df["risk"] = np.maximum(df["atr"] * 1.2, c * 0.002)
    return df


TREND_WORDS = {1: "uptrend", -1: "downtrend", 0: "sideways"}


def intraday_signal(bars: pd.DataFrame, daily: pd.DataFrame | None = None, target_r: float = 1.0) -> dict:
    if len(bars) < 60:
        return {"side": "WAIT", "summary": "Not enough intraday data yet.", "checks": []}
    f = intraday_frame(bars, daily)
    x = f.iloc[-1]
    last = float(x["close"])
    trend = int(x["trend"])
    bull = [
        ("Price is above VWAP (buyers in control today)", last > x["vwap"]),
        ("Fast average (EMA 9) is above slow average (EMA 21): short-term trend is up", x["ema9"] > x["ema21"]),
        (f"RSI {x['rsi']:.0f} shows healthy upward momentum (50-70)", 50 <= x["rsi"] <= 70),
        ("Price is above today's opening price", last > x["day_open"]),
    ]
    bear = [
        ("Price is below VWAP (sellers in control today)", last < x["vwap"]),
        ("Fast average (EMA 9) is below slow average (EMA 21): short-term trend is down", x["ema9"] < x["ema21"]),
        (f"RSI {x['rsi']:.0f} shows downward momentum (30-50)", 30 <= x["rsi"] <= 50),
        ("Price is below today's opening price", last < x["day_open"]),
    ]
    if daily is not None:
        bull.append((f"Bigger daily trend is up (it is {TREND_WORDS[trend]})", trend == 1))
        bear.append((f"Bigger daily trend is down (it is {TREND_WORDS[trend]})", trend == -1))
    side = str(x["side"])
    checks = bull if side == "BUY" or (side == "WAIT" and x["bull"] >= x["bear"]) else bear
    risk = float(x["risk"])
    sign = 1 if side == "BUY" else -1
    out = {
        "side": side,
        "agree": sum(ok for _, ok in checks),
        "of": len(checks),
        "trend": TREND_WORDS[trend],
        "checks": [{"text": t, "ok": bool(ok)} for t, ok in checks],
        "price": r2(last),
        "indicators": {"vwap": r2(x["vwap"]), "ema9": r2(x["ema9"]), "ema21": r2(x["ema21"]),
                       "rsi": round(float(x["rsi"]), 1), "atr": r2(x["atr"])},
        "risk_points": r2(risk),
    }
    if side != "WAIT":
        out.update(entry=r2(last), stop_loss=r2(last - sign * risk), target=r2(last + sign * risk * target_r))
    return out


# ---------- BTST ----------

def btst_frame(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.copy()
    rng = (d["high"] - d["low"]).replace(0, np.nan)
    d["close_pos"] = (d["close"] - d["low"]) / rng
    d["ema20"] = ema(d["close"], 20)
    d["avg_vol"] = d["volume"].shift().rolling(20).mean()
    d["vol_ratio"] = d["volume"] / d["avg_vol"].replace(0, np.nan)
    d["atr"] = atr(d)
    has_vol = d["avg_vol"].fillna(0) > 0
    d["c_strong"] = d["close_pos"] >= 0.75
    d["c_break"] = d["close"] > d["high"].shift()
    d["c_trend"] = d["close"] > d["ema20"]
    d["c_vol"] = (d["vol_ratio"] >= 1.5) & has_vol
    d["score"] = d[["c_strong", "c_break", "c_trend", "c_vol"]].sum(axis=1)
    d["need"] = np.where(has_vol, 3, 2)
    d["btst"] = d["score"] >= d["need"]
    d["risk"] = np.minimum(d["close"] - d["low"], d["atr"]).clip(lower=d["close"] * 0.003)
    return d


def btst_signal(daily: pd.DataFrame) -> dict:
    if len(daily) < 30:
        return {"side": "WAIT", "summary": "Not enough daily history.", "checks": []}
    d = btst_frame(daily)
    x = d.iloc[-1]
    has_vol = x["avg_vol"] > 0
    checks = [
        ("Closing near the day's high (buyers stayed till the end)", bool(x["c_strong"])),
        ("Broke above yesterday's high (breakout)", bool(x["c_break"])),
        ("Above the 20-day average (uptrend)", bool(x["c_trend"])),
    ]
    if has_vol:
        checks.append((f"Volume {x['vol_ratio']:.1f}x normal (big players active)", bool(x["c_vol"])))
    side = "BUY" if x["btst"] else "WAIT"
    last, risk = float(x["close"]), float(x["risk"])
    out = {"side": side, "agree": int(x["score"]), "of": len(checks),
           "checks": [{"text": t, "ok": ok} for t, ok in checks]}
    if side == "BUY":
        out.update(entry=r2(last), stop_loss=r2(last - risk), target=r2(last + risk))
    return out


# ---------- option chain ----------

def option_view(chain: list[dict], spot: float) -> dict:
    """``chain``: rows of {strike, ce: {...}, pe: {...}} with ltp/oi/iv."""
    rows = [r for r in chain if r.get("ce") or r.get("pe")]
    if not rows or not spot:
        return {}
    strikes = sorted(r["strike"] for r in rows)
    by = {r["strike"]: r for r in rows}
    atm = min(strikes, key=lambda k: abs(k - spot))

    def oi(r, side):
        return float((r.get(side) or {}).get("oi") or 0)

    ce_oi, pe_oi = sum(oi(r, "ce") for r in rows), sum(oi(r, "pe") for r in rows)
    pcr = pe_oi / ce_oi if ce_oi else 0.0
    max_pain = min(strikes, key=lambda k: sum(oi(r, "ce") * max(k - r["strike"], 0)
                                              + oi(r, "pe") * max(r["strike"] - k, 0) for r in rows))
    ivs = [v for v in ((by[atm].get("ce") or {}).get("iv"), (by[atm].get("pe") or {}).get("iv")) if v]
    return {
        "atm": atm, "pcr": round(pcr, 2), "max_pain": max_pain,
        "bias": "BULLISH" if pcr >= 1.2 else "BEARISH" if pcr <= 0.8 else "NEUTRAL",
        "support": max(rows, key=lambda r: oi(r, "pe"))["strike"],
        "resistance": max(rows, key=lambda r: oi(r, "ce"))["strike"],
        "atm_iv": round(sum(ivs) / len(ivs), 1) if ivs else None,
    }
