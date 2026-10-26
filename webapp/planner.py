"""One plain-English trade plan per instrument, checked against its own history.

The plan only says "take this trade" when the exact rule firing now has won often
enough on recent data, the bigger trend agrees, and the clock allows it. Otherwise
it says there is no safe trade and why.
"""

from __future__ import annotations

import math
from datetime import time

import numpy as np
import pandas as pd

from webapp import market_data as md, signals as sg

TARGETS = (0.5, 0.75, 1.0, 1.5)   # target as a multiple of the risk (distance to stop loss)
MIN_TRADES = 10
SAFE_WIN_RATE = 60.0               # below this the page says "no safe trade"
MIN_EDGE = 0.05                    # average result per trade, in multiples of risk, after costs
ENTRY_FROM, LAST_ENTRY, EXIT_BY = time(9, 45), time(14, 30), time(15, 15)
DEFAULT_DELTA = 0.55


# ---------- backtests ----------

def backtest_intraday(frame: pd.DataFrame, target_r: float, cost_pct: float = 0.0) -> list[dict]:
    """Replay the intraday rule: enter on the signal bar's close, exit at target, stop, or 3:15 PM.

    ``cost_pct`` (of price, round trip) stands in for brokerage, taxes and slippage; a
    trade that only just reached its target can still be a loss after costs.
    """
    times, dates = frame.index.time, frame.index.date
    o, h, lo, c = (frame[k].to_numpy() for k in ("open", "high", "low", "close"))
    side, risk = frame["side"].to_numpy(), frame["risk"].to_numpy()
    trades, pos, traded = [], None, set()
    for i in range(60, len(frame)):
        if pos:
            buy = pos["side"] == "BUY"
            r = None
            if dates[i] != pos["date"]:
                r = (c[i - 1] - pos["entry"]) / pos["risk"] * (1 if buy else -1)
            elif (lo[i] <= pos["sl"]) if buy else (h[i] >= pos["sl"]):
                r = -1.0  # stop checked first: the cautious reading of a bar that touched both
            elif (h[i] >= pos["tgt"]) if buy else (lo[i] <= pos["tgt"]):
                r = target_r
            elif times[i] >= EXIT_BY:
                r = (c[i] - pos["entry"]) / pos["risk"] * (1 if buy else -1)
            if r is not None:
                r -= pos["entry"] * cost_pct / 100 / pos["risk"]
                pos.update(r=round(float(r), 2), exit_time=str(frame.index[i]))
                trades.append(pos)
                pos = None
            continue
        # One trade a day: a second attempt after a stop-out is how small losses compound.
        if dates[i] not in traded and side[i] != "WAIT" and ENTRY_FROM <= times[i] <= LAST_ENTRY:
            traded.add(dates[i])
            sgn = 1 if side[i] == "BUY" else -1
            pos = {"side": side[i], "date": dates[i], "time": str(frame.index[i]), "entry": float(c[i]),
                   "risk": float(risk[i]), "sl": c[i] - sgn * risk[i], "tgt": c[i] + sgn * risk[i] * target_r}
    return trades


def backtest_btst(frame: pd.DataFrame) -> list[dict]:
    """Buy at the close of a BTST day; next day exit at 1R target, stop, or the close."""
    trades = []
    for i in range(25, len(frame) - 1):
        x, nx = frame.iloc[i], frame.iloc[i + 1]
        if not x["btst"]:
            continue
        entry, risk = float(x["close"]), float(x["risk"])
        sl, tgt = entry - risk, entry + risk
        if nx["open"] >= tgt or nx["open"] <= sl:
            r = (nx["open"] - entry) / risk
        elif nx["low"] <= sl:
            r = -1.0
        elif nx["high"] >= tgt:
            r = 1.0
        else:
            r = (nx["close"] - entry) / risk
        trades.append({"side": "BUY", "time": str(frame.index[i].date()), "entry": entry,
                       "exit_time": str(frame.index[i + 1].date()), "r": round(float(r), 2)})
    return trades


def stats(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0, "wins": 0, "win_rate": None, "avg_r": None}
    wins = sum(t["r"] > 0 for t in trades)
    return {"trades": n, "wins": wins, "win_rate": round(wins / n * 100, 1),
            "avg_r": round(sum(t["r"] for t in trades) / n, 2)}


def pick_target(results: dict[float, list[dict]], side: str) -> tuple[float, dict]:
    """The safest target: highest win rate that still made money on average, for this side if we can."""
    def side_stats(trades):
        own = [t for t in trades if t["side"] == side]
        return stats(own) if len(own) >= MIN_TRADES else stats(trades)

    scored = {t: side_stats(tr) for t, tr in results.items()}
    ok = [(t, s) for t, s in scored.items() if s["trades"] >= MIN_TRADES and (s["avg_r"] or 0) >= MIN_EDGE]
    if ok:
        return max(ok, key=lambda ts: (ts[1]["win_rate"], ts[1]["avg_r"]))
    return max(scored.items(), key=lambda ts: (ts[1]["avg_r"] if ts[1]["avg_r"] is not None else -9))


# ---------- market mood ----------

def market_mood(daily: pd.DataFrame, name: str) -> dict:
    c = daily["close"]
    last = float(c.iloc[-1])
    e20, e50 = float(sg.ema(c, 20).iloc[-1]), float(sg.ema(c, 50).iloc[-1])
    e200 = float(sg.ema(c, 200).iloc[-1]) if len(c) >= 200 else None
    above = sum(last > e for e in (e20, e50, e200) if e is not None)
    total = 3 if e200 is not None else 2

    if above == total and e20 > e50:
        label, tone = "Strong uptrend", "up"
    elif above >= total - 1 and last > e50:
        label, tone = "Uptrend", "up"
    elif above == 0 and e20 < e50:
        label, tone = "Strong downtrend", "down"
    elif above <= 1 and last < e50:
        label, tone = "Downtrend", "down"
    else:
        label, tone = "Sideways", "flat"

    def ret(n):
        return round((last / float(c.iloc[-n - 1]) - 1) * 100, 2) if len(c) > n else None

    year = daily.iloc[-252:]
    hi, lo = float(year["high"].max()), float(year["low"].min())
    atr_pts = float(sg.atr(daily).iloc[-1])
    pos52 = (last - lo) / (hi - lo) * 100 if hi > lo else 50
    explain = {
        "Strong uptrend": f"{name} is above its 20, 50 and 200-day averages. Buyers have been in charge for weeks; "
                          "buying dips has worked better than selling rallies.",
        "Uptrend": f"{name} is mostly above its key averages. The trend leans up, but it is not as strong.",
        "Sideways": f"{name} is moving between its averages without a clear direction. Expect choppy moves; "
                    "trades need tighter targets.",
        "Downtrend": f"{name} is mostly below its key averages. Sellers have the upper hand.",
        "Strong downtrend": f"{name} is below its 20, 50 and 200-day averages. Rallies have been sold; "
                            "buying here is fighting the trend.",
    }[label]
    return {
        "label": label, "tone": tone, "explain": explain,
        "returns": {"1 week": ret(5), "1 month": ret(21), "3 months": ret(63), "1 year": ret(252)},
        "high_52w": sg.r2(hi), "low_52w": sg.r2(lo), "pos_52w": round(pos52),
        "daily_move": sg.r2(atr_pts), "daily_move_pct": round(atr_pts / last * 100, 2),
        "averages": {"20-day": sg.r2(e20), "50-day": sg.r2(e50), "200-day": sg.r2(e200)},
        "recent": [
            {"date": str(ix.date()), "open": sg.r2(r.open), "high": sg.r2(r.high), "low": sg.r2(r.low),
             "close": sg.r2(r.close),
             "change_pct": round((r.close / prev - 1) * 100, 2) if prev else None}
            for (ix, r), prev in zip(daily.iloc[-10:].iterrows(), daily["close"].shift().iloc[-10:], strict=True)
        ][::-1],
    }


# ---------- option leg ----------

def option_leg(inst: dict, side: str, spot: float, risk_pts: float, target_pts: float) -> dict | None:
    if inst["kind"] != "INDEX" or side == "WAIT":
        return None
    step = inst["step"]
    kind = "CE" if side == "BUY" else "PE"
    # One step in the money: a higher delta tracks the index more closely than a cheap far strike.
    strike = math.floor(spot / step) * step if kind == "CE" else math.ceil(spot / step) * step
    leg = {"kind": kind, "strike": strike, "lot": inst["lot"], "premium": None, "delta": DEFAULT_DELTA,
           "expiry": None, "source": "estimate"}
    if md.dhan.enabled:
        try:
            chain = md.option_chain(inst["symbol"])
            row = next((r for r in chain["rows"] if r["strike"] == strike), None)
            x = (row or {}).get(kind.lower()) or {}
            if x.get("ltp"):
                leg.update(premium=x["ltp"], expiry=chain["expiry"], source="dhan",
                           delta=abs(x.get("delta") or DEFAULT_DELTA) or DEFAULT_DELTA, iv=x.get("iv"))
            leg["chain"] = sg.option_view(chain["rows"], chain["spot"])
        except md.DataError as exc:
            leg["chain_error"] = str(exc)
    p, d = leg["premium"], leg["delta"]
    leg["move_sl"] = sg.r2(d * risk_pts)
    leg["move_target"] = sg.r2(d * target_pts)
    if p:
        sl = max(p - d * risk_pts, p * 0.5)
        tgt = p + d * target_pts
        leg.update(stop_loss=sg.r2(sl), target=sg.r2(tgt), cost_per_lot=sg.r2(p * inst["lot"]),
                   max_loss_per_lot=sg.r2((p - sl) * inst["lot"]), profit_per_lot=sg.r2((tgt - p) * inst["lot"]),
                   gain_pct=round((tgt / p - 1) * 100), loss_pct=round((1 - sl / p) * 100))
    return leg


# ---------- the plan ----------

def build_plan(symbol: str) -> dict:
    inst = md.instrument(symbol)
    name = inst["name"]
    bars5, source = md.candles(symbol, "5m")
    daily, _ = md.candles(symbol, "1D")
    frame = sg.intraday_frame(bars5, daily)

    # Round-trip costs: index options trade at a tight spread; cash equity pays STT, charges and a wider one.
    cost = 0.01 if inst["kind"] == "INDEX" else 0.04
    results = {t: backtest_intraday(frame, t, cost) for t in TARGETS}
    side = str(frame["side"].iloc[-1])
    target_r, record = pick_target(results, side if side != "WAIT" else "BUY")
    chosen = results[target_r]
    signal = sg.intraday_signal(bars5, daily, target_r)
    mood = market_mood(daily, name)
    open_now = sg.market_open()
    t = sg.now_ist().time()

    by_side = {s: stats([x for x in chosen if x["side"] == s]) for s in ("BUY", "SELL")}
    side_rec = by_side.get(side) if side != "WAIT" and by_side[side]["trades"] >= MIN_TRADES else record
    win = side_rec["win_rate"] or 0
    against = (side == "BUY" and mood["tone"] == "down") or (side == "SELL" and mood["tone"] == "up")

    blockers = []
    if side == "WAIT":
        blockers.append("Not every condition lines up with the bigger trend, so there is no clean setup right now.")
    if side != "WAIT" and side_rec["trades"] < MIN_TRADES:
        blockers.append(f"Only {side_rec['trades']} similar trades in the data: too few to trust.")
    elif side != "WAIT" and win < SAFE_WIN_RATE:
        blockers.append(f"This setup won only {win:.0f}% of the time recently (we want {SAFE_WIN_RATE:.0f}%+).")
    if side != "WAIT" and (side_rec["avg_r"] or 0) <= 0:
        blockers.append("After costs, this setup lost money on average recently.")
    elif side != "WAIT" and (side_rec["avg_r"] or 0) < MIN_EDGE:
        blockers.append("After costs, its average profit per trade is too small to rely on.")
    if against:
        blockers.append(f"It goes against the bigger trend ({mood['label'].lower()}).")
    if open_now and t > LAST_ENTRY:
        blockers.append("It's after 2:30 PM: too late to start a new intraday trade.")
    if open_now and t < ENTRY_FROM:
        blockers.append("The first 30 minutes are noisy. Wait until 9:45 AM.")
    stale = md.stale_bars(bars5, "5m", open_now, sg.now_ist())
    if open_now and source not in ("dhan", "yahoo"):
        blockers.append(f"No live prices: this is the last {source}. Wait for the data source to come back.")
    elif stale is not None:
        blockers.append(f"The latest price bar is {stale / 60:.0f} min old: the data feed is behind, "
                        "so this plan is not current.")

    safe = not blockers
    is_index = inst["kind"] == "INDEX"
    if side == "WAIT":
        action = "NO TRADE"
    elif is_index:
        action = "BUY CALL" if side == "BUY" else "BUY PUT"
    else:
        action = "BUY" if side == "BUY" else "SELL (intraday short)"

    leg = None
    if side != "WAIT":
        leg = option_leg(inst, side, signal["entry"], abs(signal["entry"] - signal["stop_loss"]),
                         abs(signal["target"] - signal["entry"]))

    btst_now = sg.btst_signal(daily)
    btst_rec = stats(backtest_btst(sg.btst_frame(daily)))

    return {
        "symbol": inst["symbol"], "name": name, "kind": inst["kind"], "source": source,
        "market_open": open_now, "as_of": str(bars5.index[-1]),
        "data": {"last_bar_age_s": round(md.bar_age(bars5, sg.now_ist())), "stale": stale is not None,
                 "built_at": sg.now_ist().isoformat(timespec="seconds")},
        "verdict": {
            "action": action if safe else ("NO SAFE TRADE" if side != "WAIT" else "NO TRADE"),
            "setup": action, "safe": safe, "side": side, "blockers": blockers,
            "win_rate": side_rec["win_rate"], "trades": side_rec["trades"], "avg_r": side_rec["avg_r"],
            "confidence": "High" if win >= 70 else "Medium" if win >= SAFE_WIN_RATE else "Low",
            "against_trend": against,
        },
        "signal": signal,
        "target_r": target_r,
        "option": leg,
        "mood": mood,
        "record": {
            "days": len(set(frame.index.date)),
            "cost_pct": cost,
            "chosen": target_r,
            "by_target": {str(k): stats(v) for k, v in results.items()},
            "by_side": by_side,
            "last": [{k: v for k, v in tr.items() if k in ("side", "time", "entry", "exit_time", "r")}
                     for tr in chosen[-12:]][::-1],
        },
        "btst": {**btst_now, "record": btst_rec,
                 "safe": btst_now["side"] == "BUY" and (btst_rec["win_rate"] or 0) >= SAFE_WIN_RATE
                 and btst_rec["trades"] >= 5 and mood["tone"] != "down"},
    }


def _clean(o):
    """NaN is not valid JSON."""
    if isinstance(o, float) and (np.isnan(o) or np.isinf(o)):
        return None
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, np.generic):
        return _clean(o.item())
    return o


def plan(symbol: str) -> dict:
    return _clean(md._cache.get(("plan", symbol.upper()), 10, lambda: build_plan(symbol)))
