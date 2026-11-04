"""Trade Record: dummy (paper) trades taken from the AI strategist, monitored live, with a P&L history.

Two kinds, kept apart: trades **you** took (Take buttons on the Plan tab) and
**every AI suggestion**, recorded automatically and settled by the rules (at the target or stop when the index
reaches it — the stop if both — or at expiry), so the record measures how good the AI's suggestions really are,
by Pulse's evidence score. Both kinds close themselves by the same rules (your trades since 2026-11-04, user's
choice); you can still close one early by hand.

One lot per trade. Entry prices are the ones the strategist priced (buy at the ask, sell at the bid). While a trade
is open it is marked to market from the NSE option chain at the price it could be closed at now (a bought leg at the
bid, a sold leg at the ask). When the index reaches the target or stop, or a Super-order leg's premium reaches its
own (whichever first), the trade is closed at those close-out prices (the stop if both); after expiry it settles at intrinsic value. Charges for opening and closing every leg
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


def _market_open() -> bool:
    """NSE's regular session. Outside it the chain shows the last prices (NSE keeps refreshing them until about
    15:40), which no order could get: no trade is entered, closed or settled at them, except at expiry."""
    from webapp import signals

    return signals.market_open()


CLOSED_MSG = "Market band hai: abhi ke prices pe asli order nahi lag sakta. 9:15 ke baad karna."
MAX_QUOTE_AGE = 60               # seconds: an older chain snapshot is not a price you could trade at now
MAX_CLOCK_AHEAD = 30             # seconds NSE's stamp may run ahead of this computer's clock


def _stale_quotes(ch: dict, now: datetime) -> str | None:
    """Why the chain's quotes cannot be traded at now, or None. NSE stamps the whole chain (``records.timestamp``,
    IST); the quotes carry no time of their own."""
    import pytz

    ts = ch.get("timestamp")
    if not ts:
        return "the chain has no timestamp, so its quotes may be old"
    try:
        when = pytz.timezone("Asia/Kolkata").localize(datetime.strptime(ts, "%d-%b-%Y %H:%M:%S"))
    except ValueError:
        return f"the chain's timestamp {ts!r} could not be read"
    if when.date() != now.date():
        return f"the quotes are from {ts[:11]}, not today"
    age = (now - when).total_seconds()
    if age < -MAX_CLOCK_AHEAD:
        return f"NSE's time ({ts[-8:]}) is {-age:.0f} s ahead of this computer's clock: check the clock"
    if age > MAX_QUOTE_AGE:
        return f"the quotes are {age:.0f} s old (limit {MAX_QUOTE_AGE} s)"
    return None


EXPIRED_MSG = "Yeh run expired hai (kisi aur din ka): uske prices aaj ke nahi. Analysis dobara chala, phir Take kar."


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


RANGE = ("iron_condor",)        # range trades: profit while the index stays between the sold strikes


def _range(legs: list[dict]) -> list[float]:
    """A range trade's profit zone: from its sold put to its sold call."""
    return [min(x["strike"] for x in legs if x["action"] == "SELL" and x["type"] == "PE"),
            max(x["strike"] for x in legs if x["action"] == "SELL" and x["type"] == "CE")]


def _as_range_trade(t: dict) -> None:
    """A range trade has no single index target or stop (the strategist's one-target model does not fit it): it is
    held while the index stays inside the sold strikes and closed when the index leaves them, or at expiry."""
    t["range"] = _range(t["legs"])
    t["index_target"] = t["index_stop"] = None
    for leg in t["legs"]:                                # premiums "at the target / stop" of levels that do not apply
        leg["target"] = leg["stop"] = None


def take_from_run(run_id: str, candidate: int, chain_fn=None, source: str = "you") -> dict:
    """Your Take on candidate ``candidate`` of AI run ``run_id``, priced here and now: the run must be today's
    (IST), the market open, the index inside the candidate's entry zone, and every leg quoted on both sides in a
    fresh chain. The entry is that chain's ask for a bought leg and bid for a sold one; the run's price is kept
    beside it. Nothing the page sends is used except the two ids."""
    from webapp import option_chain as oc, signals, strategist as st

    run = st.load_run(run_id or "")
    if not run:
        raise TradeError("This run is not on file: run the analysis again.")
    if st.run_expired(run):
        raise TradeError(EXPIRED_MSG)
    if not _market_open():
        raise TradeError(CLOSED_MSG)
    trades = run.get("trades") or []
    if not 0 <= candidate < len(trades):
        raise TradeError(f"This run has no trade #{candidate + 1}.")
    c = trades[candidate]
    try:
        ch = (chain_fn or oc.chain)(c["symbol"], c["expiry"])
    except Exception as exc:                               # never fall back to the run's prices
        raise TradeError(f"Live prices unavailable ({str(exc)[:160]}): not taken. Try again in a moment.") from exc
    if why := _stale_quotes(ch, signals.now_ist()):
        raise TradeError(f"NSE: {why}. Not taken; try again in a moment.")
    plan, spot = c["plan"], ch["spot"]
    lo, hi = plan.get("underlying_entry_low"), plan.get("underlying_entry_high")
    if lo is not None and hi is not None and not lo <= spot <= hi:
        raise TradeError(f"{c['symbol']} is at {spot:,.2f}, outside this trade's entry zone {lo:,.0f}-{hi:,.0f}: not taken.")
    rows = {r["strike"]: r for r in ch["rows"]}
    for leg in plan["legs"]:
        q = (rows.get(float(leg["strike"])) or {}).get(leg["option_type"].lower())
        if not q or not q.get("bid") or not q.get("ask"):
            raise TradeError(f"{leg['strike']:,.0f} {leg['option_type']} has no live bid / ask right now: not taken.")
    sp = st.StrategyPlan(**plan)
    priced = st.price(sp, ch)
    days = (datetime.strptime(c["expiry"], "%d-%b-%Y").date() - signals.now_ist().date()).days
    fresh = c | {"spot": spot, "priced": priced, "levels": st.trade_levels(sp, priced, ch, days), "charges_per_lot": st.charges(priced, 1)}
    shown = {(x["strike"], x["type"], x["action"]): x["price"] for x in c["priced"]["legs"]}
    return take(fresh, source=source, provenance={"run_id": run_id, "candidate": candidate, "run_asked_at": run.get("asked_at"),
                                                  "spot_at_run": c.get("spot")}, shown=shown)


def record_ai_pick(run_id: str, chain_fn=None) -> dict:
    """The AI's #1 of a run, into the AI track record through the same fresh-chain path as your Take. A refusal
    (stale quotes, outside the entry zone, no live quote...) is kept as a "not taken" row with its reason, so a
    missed pick shows instead of a trade at an old price."""
    from webapp import strategist as st

    try:
        return take_from_run(run_id, 0, chain_fn, source="ai")
    except TradeError as exc:
        c = ((st.load_run(run_id) or {}).get("trades") or [None])[0]
        if c is None:
            raise
        plan = c["plan"]
        row = {"id": uuid.uuid4().hex[:10], "taken_at": _now(), "status": "not_taken", "reason": str(exc), "source": "ai",
               "symbol": c["symbol"], "expiry": c["expiry"], "strategy": plan["strategy"], "bias": plan.get("bias"),
               "index_target": plan.get("underlying_target"), "index_stop": plan.get("underlying_stop"),
               "legs": [{"action": x["action"], "type": x["type"], "strike": x["strike"], "shown_price": x["price"]} for x in c["priced"]["legs"]],
               "ai_confidence": plan.get("confidence"), "run_id": run_id, "candidate": 0, "spot_at_run": c.get("spot")}
        with _lock:
            trades = _load()
            trades.append(row)
            _save(trades)
        return row


def take(result: dict, source: str = "you", provenance: dict | None = None, shown: dict | None = None) -> dict:
    """Record the strategist's proposal (``recommend``'s result) as an open one-lot paper trade.
    ``source``: "you" (taken on the Plan tab) or "ai" (every suggestion, recorded automatically)."""
    plan, priced = result.get("plan") or {}, result.get("priced")
    if result.get("rejected") or not priced or plan.get("strategy") in (None, "no_trade"):
        raise TradeError("There is no trade to take in this suggestion.")
    if not _market_open():
        raise TradeError(CLOSED_MSG)
    lv = {(x["strike"], x["type"], x["action"]): x for x in (result.get("levels") or {}).get("legs", [])}
    legs = []
    for x in priced["legs"]:
        m = lv.get((x["strike"], x["type"], x["action"]), {})
        legs.append({"action": x["action"], "type": x["type"], "strike": x["strike"], "id": x.get("id"),
                     "entry": x["price"], "target": m.get("premium_at_target"), "stop": m.get("premium_at_stop")}
                    | ({"shown_price": shown.get((x["strike"], x["type"], x["action"]))} if shown else {}))
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
    }
    trade |= provenance or {}
    if trade["strategy"] in RANGE:
        _as_range_trade(trade)
    with _lock:
        trades = _load()
        if provenance:                                   # a double click on the same run's trade: one trade
            again = next((t for t in trades if t.get("run_id") == provenance["run_id"]
                          and t.get("candidate") == provenance["candidate"] and t.get("source") == source), None)
            if again:
                return again
        if source == "ai":                               # the same trade again (a re-run, same strikes): counted once
            same = next((t for t in trades if t["status"] == "open" and t.get("source") == "ai" and _same(t, trade)), None)
            if same:
                return same
        trades.append(trade)
        _save(trades)
    return trade


def _same(a: dict, b: dict) -> bool:
    key = lambda t: (t["symbol"], t["expiry"], t["strategy"], sorted((x["action"], x["type"], x["strike"]) for x in t["legs"]))  # noqa: E731
    return key(a) == key(b)


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


CREDIT = ("bear_call_spread", "bull_put_spread")


def _super_legs(trade: dict) -> list[int]:
    """Legs that carry a Dhan Super order (target + stop on the premium): a single leg, or a credit spread's sold leg.
    Debit spreads and condors are closed by hand on the index level, so they have none."""
    legs = trade["legs"]
    if len(legs) == 1:
        return [0]
    return [i for i, x in enumerate(legs) if x["action"] == "SELL"] if trade.get("strategy") in CREDIT else []


def _flags(trade: dict, spot: float | None, ltps: list[float | None] | None = None) -> list[str]:
    """Which of target / stop is reached now, whichever comes first (user's choice, 2026-11-04): the index level
    (bearish: target below, stop above), or a Super-order leg's premium at its last traded price, as Dhan triggers."""
    out, tgt, stop = [], trade.get("index_target"), trade.get("index_stop")
    if trade.get("range"):                               # a range trade: the stop is the index leaving its sold strikes
        lo, hi = trade["range"]
        return ["stop"] if spot is not None and not lo < spot < hi else []
    if spot is not None and tgt is not None and stop is not None:
        down = tgt < stop
        if (spot <= tgt) if down else (spot >= tgt):
            out.append("target")
        if (spot >= stop) if down else (spot <= stop):
            out.append("stop")
    for i in _super_legs(trade) if ltps else []:
        leg, px = trade["legs"][i], ltps[i]
        if px is None or leg.get("target") is None or leg.get("stop") is None:
            continue
        buy = leg["action"] == "BUY"                     # a sold leg gains when its premium falls
        if (px >= leg["target"]) if buy else (px <= leg["target"]):
            out.append("target")
        if (px <= leg["stop"]) if buy else (px >= leg["stop"]):
            out.append("stop")
    return list(dict.fromkeys(out))


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
    view["flags"] = _flags(trade, ch["spot"], [x["ltp"] for x in view["legs"]])
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
    """Open trades with live marks (flags saved; every trade settled by the rules), closed trades, totals —
    yours and the AI's separately, the AI's also by evidence score."""
    live = _market_open()
    with _lock:
        trades = _load()
        changed = _repair_range_trades(trades)
        for t in trades:
            if t["status"] != "open":
                continue
            v = mark(t, chain_fn)
            v["market_closed"] = not live
            if not live and "expired" not in v["flags"]:
                v["flags"] = []                          # last prices of a closed market: shown, never acted on
                t["live"] = v
                continue
            if v.get("spot") is not None and v["spot"] != t.get("last_spot"):
                t["last_spot"] = v["spot"]
                changed = True
            changed |= _remember_flags(t, v)
            changed |= _auto_settle(t, v)
            t["live"] = v
        if changed:
            _save([{k: x for k, x in t.items() if k != "live"} for t in trades])
    out = {}
    for who in ("you", "ai"):
        mine = [t for t in trades if t.get("source", "you") == who]
        open_ = sorted((t for t in mine if t["status"] == "open"), key=lambda t: t["taken_at"], reverse=True)
        closed = sorted((t for t in mine if t["status"] == "closed"), key=lambda t: t["closed_at"], reverse=True)
        out[who] = {"open": open_, "closed": closed, "stats": _stats(closed, open_),
                    "not_taken": sorted((t for t in mine if t["status"] == "not_taken"), key=lambda t: t["taken_at"], reverse=True)}
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
    """Close by rule: the stop first if both are reached, then the target, else at expiry."""
    if "expired" in v["flags"]:
        spot = t.get("last_spot") or t["spot_at_entry"]
        _settle(t, [_intrinsic(leg, spot) for leg in t["legs"]], spot, "expired")
        return True
    hit = "stop" if "stop" in v["flags"] else "target" if "target" in v["flags"] else None
    if hit and v["pnl"] is not None:
        _settle(t, [x["now"] for x in v["legs"]], v["spot"], "range broken" if t.get("range") else f"{hit} reached")
        return True
    return False


BUG_NOTE = ("reopened 2026-11-04: it had been closed by a bug that read this range trade's single index target / stop "
            "as a directional trade's")


def _repair_range_trades(trades: list[dict]) -> bool:
    """Range trades recorded before the range rule: give them their range, and reopen any that the old rule closed
    by an index target or stop (it was never a real exit). Runs once per trade: afterwards each carries a range."""
    changed = False
    for t in trades:
        if t.get("strategy") not in RANGE or t.get("range"):
            continue
        _as_range_trade(t)
        if t["status"] == "closed" and t.get("reason") in ("target reached", "stop reached"):
            for k in ("closed_at", "spot_at_exit", "reason", "gross_pnl", "net_pnl"):
                t.pop(k, None)
            for leg in t["legs"]:
                leg.pop("exit", None)
            t.update(status="open", alerts=[], note=BUG_NOTE)
        changed = True
    return changed


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
        elif not _market_open():
            raise TradeError(CLOSED_MSG)
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
    closed still closes the trade at that minute's prices."""
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
