"""Trade Record: dummy (paper) trades taken from the AI strategist, monitored live, with a P&L history.

Two kinds, kept apart: trades **you** took (button on the Plan tab; flagged at target / stop, closed by you) and
**every AI suggestion**, recorded automatically and settled by the rules (at the target or stop when the index
reaches it — the stop if both — or at expiry), so the record measures how good the AI's suggestions really are,
by Pulse's evidence score.

One lot per trade. Entry prices are the ones the strategist priced (buy at the ask, sell at the bid). While a trade
is open it is marked to market from the NSE option chain at the price it could be closed at now (a bought leg at the
bid, a sold leg at the ask). When the index reaches the AI's target or stop, or the expiry passes, the trade is
flagged — never closed automatically (user's choice); the user closes it. Charges for opening and closing every leg
are subtracted. Stored in ``reports/trade_record/trades.json`` (git-ignored; stays on this computer).
Paper trades only: nothing here places an order.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "reports" / "trade_record" / "trades.json"
_lock = threading.Lock()


class TradeError(Exception):
    pass


def _load() -> list[dict]:
    try:
        return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else []
    except (OSError, ValueError):
        return []


def _save(trades: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(trades, indent=1, default=str), encoding="utf-8")
    tmp.replace(STORE)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def take(result: dict, source: str = "you") -> dict:
    """Record the strategist's proposal (``recommend``'s result) as an open one-lot paper trade.
    ``source``: "you" (taken on the Plan tab) or "ai" (every suggestion, recorded automatically)."""
    plan, priced = result.get("plan") or {}, result.get("priced")
    if result.get("rejected") or not priced or plan.get("strategy") in (None, "no_trade"):
        raise TradeError("There is no trade to take in this suggestion.")
    lv = {(x["strike"], x["type"], x["action"]): x for x in (result.get("levels") or {}).get("legs", [])}
    legs = []
    for x in priced["legs"]:
        m = lv.get((x["strike"], x["type"], x["action"]), {})
        legs.append({"action": x["action"], "type": x["type"], "strike": x["strike"], "id": x.get("id"),
                     "entry": x["price"], "target": m.get("premium_at_target"), "stop": m.get("premium_at_stop")})
    rng = result.get("levels") if (result.get("levels") or {}).get("kind") == "range" else None
    trade = {
        "id": uuid.uuid4().hex[:10], "taken_at": _now(), "status": "open", "lots": 1,
        "symbol": result["symbol"], "expiry": result["expiry"], "lot": priced["lot"],
        "strategy": plan["strategy"], "strategy_text": result.get("strategy_text"), "bias": plan.get("bias"),
        "spot_at_entry": result.get("spot"), "entry_low": plan.get("underlying_entry_low"),
        "entry_high": plan.get("underlying_entry_high"), "index_target": plan.get("underlying_target"),
        "index_stop": plan.get("underlying_stop"), "net_entry": priced["net_per_unit"], "debit": priced["debit"],
        "max_loss_per_lot": priced["max_loss_per_lot"], "max_profit_per_lot": priced["max_profit_per_lot"],
        "charges": result.get("charges_per_lot"), "legs": legs, "alerts": [], "source": source,
        "score": (result.get("evidence") or {}).get("score"), "score_label": (result.get("evidence") or {}).get("label"),
        "ai_confidence": plan.get("confidence"), "last_spot": result.get("spot"),
        # a range trade: stop if the index leaves [low, high], target once the position buys back for buy_back_at
        "index_range": [rng["low"], rng["high"]] if rng else None, "buy_back_at": rng["buy_back_at"] if rng else None,
    }
    with _lock:
        trades = _load()
        trades.append(trade)
        _save(trades)
    return trade


def _expired(trade: dict, today: date | None = None) -> bool:
    exp = datetime.strptime(trade["expiry"], "%d-%b-%Y").date()
    now = datetime.now()
    today = today or now.date()
    return today > exp or (today == exp and (now.hour, now.minute) >= (15, 30))


def _exit_price(leg: dict, q: dict | None) -> float | None:
    """What the leg could be closed at now: a bought leg sells at the bid, a sold leg buys back at the ask."""
    if not q:
        return None
    px = q["bid"] if leg["action"] == "BUY" else q["ask"]
    return px or q["ltp"] or None


def _intrinsic(leg: dict, spot: float) -> float:
    return max(0.0, spot - leg["strike"]) if leg["type"] == "CE" else max(0.0, leg["strike"] - spot)


def _pnl(trade: dict, exits: list[float]) -> float:
    return sum((x - leg["entry"]) * (1 if leg["action"] == "BUY" else -1)
               for leg, x in zip(trade["legs"], exits, strict=True)) * trade["lot"] * trade["lots"]


def _flags(trade: dict, spot: float | None, exits: list | None = None) -> list[str]:
    """Which of target / stop the trade has reached now (bearish: target below, stop above). A range trade stops when
    the index leaves its range, and reaches its target when the position can be bought back for ``buy_back_at``."""
    if trade.get("index_range"):
        out, (low, high) = [], trade["index_range"]
        if exits and None not in exits and trade.get("buy_back_at") is not None:
            cost = sum((x if leg["action"] == "SELL" else -x) for leg, x in zip(trade["legs"], exits, strict=True))
            if cost <= trade["buy_back_at"]:
                out.append("target")
        if spot is not None and (spot <= low or spot >= high):
            out.append("stop")
        return out
    out, tgt, stop = [], trade.get("index_target"), trade.get("index_stop")
    if spot is None or tgt is None or stop is None:
        return out
    down = tgt < stop
    if (spot <= tgt) if down else (spot >= tgt):
        out.append("target")
    if (spot >= stop) if down else (spot <= stop):
        out.append("stop")
    return out


def mark(trade: dict, chain_fn=None) -> dict:
    """Live view of an open trade: index now, each leg's close-out price, P&L, and any target / stop / expiry flag
    (flags are remembered with the time they first happened)."""
    from webapp import option_chain as oc

    view = {"spot": None, "legs": [], "pnl": None, "flags": [], "error": None, "as_of": None}
    if _expired(trade):
        view["flags"].append("expired")
        return view
    try:
        ch = (chain_fn or oc.chain)(trade["symbol"], trade["expiry"])
    except Exception as exc:
        view["error"] = f"Live prices unavailable: {str(exc)[:160]}"
        return view
    rows = {r["strike"]: r for r in ch["rows"]}
    exits = []
    for leg in trade["legs"]:
        q = (rows.get(float(leg["strike"])) or {}).get(leg["type"].lower())
        x = _exit_price(leg, q)
        exits.append(x)
        view["legs"].append({"now": x, "ltp": q["ltp"] if q else None})
    view["spot"], view["as_of"] = ch["spot"], ch.get("timestamp")
    if None not in exits:
        view["pnl"] = _pnl(trade, exits)
    view["flags"] = _flags(trade, ch["spot"], exits)
    return view


def _remember_flags(trade: dict, view: dict) -> bool:
    seen = {a["kind"] for a in trade["alerts"]}
    new = [f for f in view["flags"] if f not in seen]
    for f in new:
        trade["alerts"].append({"kind": f, "at": _now(), "spot": view.get("spot"), "pnl": view.get("pnl")})
    return bool(new)


def _stats(closed: list[dict], open_: list[dict]) -> dict:
    nets = [t["net_pnl"] for t in closed]
    wins = [x for x in nets if x > 0]
    return {"closed": len(closed), "open": len(open_), "net": sum(nets), "wins": len(wins),
            "losses": len([x for x in nets if x <= 0]), "win_rate": len(wins) / len(nets) * 100 if nets else None,
            "avg": sum(nets) / len(nets) if nets else None, "best": max(nets, default=None),
            "worst": min(nets, default=None), "open_pnl": sum((t.get("live") or {}).get("pnl") or 0 for t in open_)}


def overview(chain_fn=None) -> dict:
    """Open trades with live marks (flags saved; AI suggestions settled by the rules), closed trades, totals —
    yours and the AI's separately, the AI's also by evidence score."""
    with _lock:
        trades = _load()
        changed = False
        for t in trades:
            if t["status"] != "open":
                continue
            v = mark(t, chain_fn)
            if v.get("spot") is not None and v["spot"] != t.get("last_spot"):
                t["last_spot"] = v["spot"]
                changed = True
            changed |= _remember_flags(t, v)
            if t.get("source") == "ai":
                changed |= _auto_settle(t, v)
            t["live"] = v
        if changed:
            _save([{k: x for k, x in t.items() if k != "live"} for t in trades])
    out = {}
    for who in ("you", "ai"):
        mine = [t for t in trades if t.get("source", "you") == who]
        open_ = sorted((t for t in mine if t["status"] == "open"), key=lambda t: t["taken_at"], reverse=True)
        closed = sorted((t for t in mine if t["status"] == "closed"), key=lambda t: t["closed_at"], reverse=True)
        out[who] = {"open": open_, "closed": closed, "stats": _stats(closed, open_)}
    out["ai"]["by_score"] = {band: _stats([t for t in out["ai"]["closed"] if t.get("score_label") == band], [])
                             for band in ("Strong", "Moderate", "Weak")}
    # the page's original keys stay = your trades
    return out | {"open": out["you"]["open"], "closed": out["you"]["closed"], "stats": out["you"]["stats"]}


def _settle(t: dict, exits: list[float], spot: float | None, reason: str) -> dict:
    gross = _pnl(t, exits)
    fee = _charges(t, exits)
    t.update(status="closed", closed_at=_now(), spot_at_exit=spot, reason=reason, gross_pnl=gross, charges=fee,
             net_pnl=gross - fee)
    for leg, x in zip(t["legs"], exits, strict=True):
        leg["exit"] = x
    return t


def _auto_settle(t: dict, v: dict) -> bool:
    """AI suggestions close by rule: the stop first if both are reached, then the target, else at expiry."""
    if "expired" in v["flags"]:
        spot = t.get("last_spot") or t["spot_at_entry"]
        _settle(t, [_intrinsic(leg, spot) for leg in t["legs"]], spot, "expired")
        return True
    hit = "stop" if "stop" in v["flags"] else "target" if "target" in v["flags"] else None
    if hit and v["pnl"] is not None:
        _settle(t, [x["now"] for x in v["legs"]], v["spot"], f"{hit} reached")
        return True
    return False


def close(trade_id: str, chain_fn=None) -> dict:
    """Close an open trade at the live close-out prices (after expiry: at intrinsic value from the last index level)."""
    from webapp import option_chain as oc

    with _lock:
        trades = _load()
        t = next((x for x in trades if x["id"] == trade_id), None)
        if t is None:
            raise TradeError("Unknown trade.")
        if t["status"] != "open":
            raise TradeError("This trade is already closed.")
        if _expired(t):
            spot = t.get("last_spot") or t["spot_at_entry"]
            exits = [_intrinsic(leg, spot) for leg in t["legs"]]
            reason = "expired"
        else:
            v = mark(t, chain_fn or oc.chain)
            if v["error"] or v["pnl"] is None:
                raise TradeError(v["error"] or "A leg has no live price; try again in a moment.")
            exits, spot = [x["now"] for x in v["legs"]], v["spot"]
            reason = " + ".join(f"{a['kind']} reached" for a in t["alerts"]) or "closed by you"
        _settle(t, exits, spot, reason)
        _save(trades)
        return t


def _charges(trade: dict, exits: list[float]) -> float:
    from tradingagents.analytics import costs

    qty = trade["lot"] * trade["lots"]
    total = 0.0
    for leg, x in zip(trade["legs"], exits, strict=True):
        side_in = "buy" if leg["action"] == "BUY" else "sell"
        total += costs.fill_charges(costs.OPTIONS, qty, leg["entry"], side_in)
        if x:                                             # an option that expired worthless has no exit order
            total += costs.fill_charges(costs.OPTIONS, qty, x, "sell" if side_in == "buy" else "buy")
    return total


def delete(trade_id: str) -> None:
    with _lock:
        trades = _load()
        keep = [t for t in trades if t["id"] != trade_id]
        if len(keep) == len(trades):
            raise TradeError("Unknown trade.")
        _save(keep)


# ---------------------------------------------------------------- background monitor

_monitor_started = False


def start_monitor(every_seconds: int = 60) -> None:
    """Check open trades once a minute while the market is open, so a target / stop reached while the page is
    closed is still recorded with its time."""
    global _monitor_started
    if _monitor_started:
        return
    _monitor_started = True

    def loop():
        import time

        from webapp import signals
        while True:
            time.sleep(every_seconds)
            try:
                if signals.market_open() and any(t["status"] == "open" for t in _load()):
                    overview()
            except Exception:                              # a failed check must not stop the monitor
                pass

    threading.Thread(target=loop, daemon=True, name="trade-record-monitor").start()
