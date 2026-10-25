"""AI options strategist for the Plan tab: one instrument, the user's risk limit, a defined-risk strategy or none.

Flow: gather everything known about the instrument (trend and indicators, today's rule check, expected move, regime,
implied vol vs forecast, the live option chain with its OI walls and PCR, FII positioning, the 8:30 AI view) →
one structured LLM call proposes a market read, a strategy from a fixed menu, its strikes and the underlying's
entry / target / stop with reasons → **the code** checks and prices it:

- only defined-risk structures (no naked selling — proof plan, risk limit 1); strikes must be on the chain;
- legs priced at the real bid / ask (buy at the ask, sell at the bid); max loss, max profit, break-evens computed here;
- figures per lot, with the charges for one lot in and out; the user chooses the number of lots.

Research and decision support only; no strategy here has passed the project's validation tests.
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

STRATEGIES = {
    # name: (description, legs as (action, type) in strike order low -> high)
    "no_trade": ("Stay out", []),
    "long_call": ("Buy a call: profits if the price rises, loss limited to the premium", [("BUY", "CE")]),
    "long_put": ("Buy a put: profits if the price falls, loss limited to the premium", [("BUY", "PE")]),
    "bull_call_spread": ("Buy a call, sell a higher call: cheaper bullish bet, capped profit", [("BUY", "CE"), ("SELL", "CE")]),
    "bear_put_spread": ("Buy a put, sell a lower put: cheaper bearish bet, capped profit", [("SELL", "PE"), ("BUY", "PE")]),
    "bull_put_spread": ("Sell a put, buy a lower put: earns premium if the price stays above the sold put",
                        [("BUY", "PE"), ("SELL", "PE")]),
    "bear_call_spread": ("Sell a call, buy a higher call: earns premium if the price stays below the sold call",
                         [("SELL", "CE"), ("BUY", "CE")]),
    "iron_condor": ("Sell a put spread and a call spread: earns premium if the price stays in a range",
                    [("BUY", "PE"), ("SELL", "PE"), ("SELL", "CE"), ("BUY", "CE")]),
}


class Leg(BaseModel):
    action: Literal["BUY", "SELL"]
    option_type: Literal["CE", "PE"]
    strike: float


class Level(BaseModel):
    price: float
    label: str = Field(description="what the level is, e.g. 'support: biggest put OI', '20-day average'")


class StrategyPlan(BaseModel):
    market_read: str = Field(description="3-5 plain sentences on this instrument's situation right now")
    bias: Literal["bullish", "bearish", "neutral", "unclear"]
    strategy: Literal["no_trade", "long_call", "long_put", "bull_call_spread", "bear_put_spread", "bull_put_spread",
                      "bear_call_spread", "iron_condor"]
    legs: list[Leg] = Field(description="the option legs; empty for no_trade")
    buy_or_sell_reasoning: str = Field(description="why buying or selling options suits the conditions (IV vs forecast, expected move, time to expiry)")
    strike_reasoning: str = Field(description="why these strikes (OI walls, expected range, delta / distance from spot)")
    underlying_entry_low: float | None = None
    underlying_entry_high: float | None = None
    underlying_target: float | None = None
    underlying_stop: float | None = None
    exit_plan: str = Field(description="when to book profit, cut the loss, and the time exit")
    key_levels: list[Level] = []
    risks: list[str] = []
    confidence: Literal["low", "medium", "high"]


SYSTEM = """You are a careful options strategist for Indian markets (NSE). You analyse ONE instrument from the data
given and propose at most one DEFINED-RISK options strategy for the expiry given, or no_trade.

Rules:
- Use only the strikes listed in the option chain. Never sell an option without a protective bought option of the same
  type further out of the money (spreads / iron condor only).
- Choose buying (long options, debit spreads) vs selling (credit spreads, iron condor) from the evidence: implied vol
  vs the volatility forecast (expensive options favour selling, cheap favour buying), the expected move vs the distance
  to strikes, trend and momentum, OI walls (biggest call OI = resistance, biggest put OI = support), days to expiry.
- Work out the economics from the bid / ask before choosing (buy at the ask, sell at the bid): net premium, max loss,
  max profit. Avoid credit spreads whose max profit is under half the max loss (they must win most of the time just to
  break even after costs); widen the strikes, move them closer to the money, use a debit structure, or choose no_trade.
- Entry range, target and stop are levels of the UNDERLYING (index or stock price), consistent with the expected move
  and key levels. Stop must be on the losing side of entry; target on the winning side.
- Prefer no_trade when signals conflict, the trend fights the setup, or the reward does not justify the risk.
  No strategy in this system has a proven edge; say so plainly where relevant.
- Be specific to this instrument and these numbers. Plain English, no hype."""


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def build_context(symbol: str, expiry: str | None = None) -> tuple[dict, dict]:
    """(context for the LLM, the option chain used)."""
    from webapp import morning, option_chain as oc, planner

    ch = oc.chain(symbol, expiry)
    ctx: dict = {"instrument": symbol, "time_ist": datetime.now().strftime("%Y-%m-%d %H:%M"), "spot": ch["spot"],
                 "lot_size": ch["lot"], "expiry": ch["expiry"]}
    try:
        exp = datetime.strptime(ch["expiry"], "%d-%b-%Y").date()
        ctx["days_to_expiry"] = (exp - date.today()).days
    except ValueError:
        pass
    try:
        p = planner.plan(symbol)
        m = p["mood"]
        ctx["trend"] = {k: m.get(k) for k in ("label", "explain", "returns", "averages", "pos_52w", "low_52w", "high_52w",
                                              "daily_move", "daily_move_pct")}
        ctx["recent_sessions"] = m.get("recent", [])[:5]
        s = p["signal"]
        ctx["intraday_rule"] = {"side": s.get("side"), "checks": [c["text"] + (" ✓" if c["ok"] else " ✗") for c in s.get("checks", [])],
                                "verdict": p["verdict"].get("action"), "recent_win_rate": p["verdict"].get("win_rate"),
                                "recent_avg_r": p["verdict"].get("avg_r")}
    except Exception as exc:
        ctx["trend_error"] = str(exc)[:200]
    try:
        mc = morning.context(symbol, date.today())
    except Exception as exc:                                      # e.g. a stock without a volatility forecast
        mc = {"context_error": str(exc)[:200]}
    ctx["expected_move"] = mc.get("expected_move")
    ctx["regime"] = mc.get("regime")
    ctx["implied_vol_vs_forecast"] = mc.get("iv")
    ctx["pcr_history"] = mc.get("pcr")
    ctx["fii_index_futures_long_share"] = mc.get("fii_long_share")
    plan = morning.load()
    ai = ((plan or {}).get("indices", {}).get(symbol) or {}).get("ai") or {}
    if ai.get("decision"):
        ctx["morning_ai_view"] = {"rating": ai.get("rating"), "decision_excerpt": ai["decision"][:1800]}
    rows = ch["rows"]
    i = [r["strike"] for r in rows].index(ch["atm"]) if ch["atm"] in [r["strike"] for r in rows] else len(rows) // 2
    near = rows[max(0, i - 8): i + 9]
    ctx["option_chain"] = {"summary": ch["summary"], "strikes": [
        {"strike": r["strike"], "pcr": _num(r["pcr"]),
         **{f"{side}_{k}": _num((r[side] or {}).get(k)) for side in ("ce", "pe") for k in ("ltp", "bid", "ask", "oi", "chg_oi", "iv")}}
        for r in near]}
    ctx["research_notes"] = [
        "No trading signal in this system has passed validation (walk-forward, real costs, unseen years).",
        "Measured closing bid-ask spreads are ~1-2% of premium near the money; multi-leg trades pay them on every leg.",
        "Selling option structures around company results lost money after costs in testing.",
        "GARCH expected move and the calm/choppy/stress regime are validated as RISK inputs (size of moves), not direction.",
    ]
    return ctx, ch


def ask_llm(ctx: dict) -> StrategyPlan:
    from tradingagents.default_config import build_default_config
    from tradingagents.llm_clients import create_tier_client

    llm = create_tier_client(build_default_config(), "deep").get_llm().with_structured_output(StrategyPlan)
    user = f"The app prices the legs and shows per-lot figures; do not size.\n\nDATA:\n{json.dumps(ctx, default=str)}"
    return llm.invoke([("system", SYSTEM), ("user", user)])


# ---------------------------------------------------------------- checks and pricing (no LLM)

def check_structure(plan: StrategyPlan, chain: dict) -> list[str]:
    """Problems that make the proposal unsafe or impossible; empty when it is fine."""
    if plan.strategy == "no_trade":
        return []
    shape = STRATEGIES[plan.strategy][1]
    legs = sorted(plan.legs, key=lambda x: (x.strike, x.option_type))
    problems = []
    if len(legs) != len(shape):
        return [f"{plan.strategy} needs {len(shape)} legs, got {len(legs)}"]
    strikes = {r["strike"]: r for r in chain["rows"]}
    for leg in legs:
        row = strikes.get(float(leg.strike))
        side = (row or {}).get(leg.option_type.lower()) if row else None
        if side is None:
            problems.append(f"{leg.strike:g} {leg.option_type} is not on the option chain")
    if plan.strategy == "iron_condor":
        puts = sorted((x for x in legs if x.option_type == "PE"), key=lambda x: x.strike)
        calls = sorted((x for x in legs if x.option_type == "CE"), key=lambda x: x.strike)
        ok = ([x.action for x in puts] == ["BUY", "SELL"] and [x.action for x in calls] == ["SELL", "BUY"]
              and puts[-1].strike < calls[0].strike)
        if not ok:
            problems.append("an iron condor is buy put < sell put < sell call < buy call")
    elif [(x.action, x.option_type) for x in sorted(legs, key=lambda x: x.strike)] != shape:
        problems.append(f"the legs do not form a {plan.strategy.replace('_', ' ')}")
    for leg in legs:                                              # no naked short
        if leg.action == "SELL":
            cover = [x for x in legs if x.action == "BUY" and x.option_type == leg.option_type and
                     (x.strike > leg.strike if leg.option_type == "CE" else x.strike < leg.strike)]
            if not cover:
                problems.append(f"the sold {leg.strike:g} {leg.option_type} has no protective bought option")
    return problems


def price(plan: StrategyPlan, chain: dict) -> dict:
    """Per-unit and per-lot economics at the real bid / ask."""
    rows = {r["strike"]: r for r in chain["rows"]}
    lot = chain["lot"]
    legs, net = [], 0.0                                          # net > 0: credit received
    for leg in plan.legs:
        q = rows[float(leg.strike)][leg.option_type.lower()]
        px = (q["ask"] or q["ltp"]) if leg.action == "BUY" else (q["bid"] or q["ltp"])
        net += px if leg.action == "SELL" else -px
        legs.append({"action": leg.action, "type": leg.option_type, "strike": leg.strike, "price": px, "ltp": q["ltp"],
                     "bid": q["bid"], "ask": q["ask"], "iv": q["iv"], "oi": q["oi"]})
    spot = chain["spot"]
    calls = sorted(x.strike for x in plan.legs if x.option_type == "CE")
    puts = sorted(x.strike for x in plan.legs if x.option_type == "PE")
    width = max((calls[-1] - calls[0]) if len(calls) == 2 else 0, (puts[-1] - puts[0]) if len(puts) == 2 else 0)
    s = plan.strategy
    if s in ("long_call", "long_put"):
        max_loss, max_profit = -net, None                         # premium paid; profit open-ended
        k = plan.legs[0].strike
        breakevens = [k - net] if s == "long_call" else [k + net]
    elif s in ("bull_call_spread", "bear_put_spread"):
        max_loss, max_profit = -net, width + net
        low, high = (calls if s == "bull_call_spread" else puts)
        breakevens = [low - net] if s == "bull_call_spread" else [high + net]
    else:                                                         # credit spreads, iron condor
        max_profit, max_loss = net, width - net
        breakevens = []
        if puts:
            breakevens.append(puts[-1] - net)
        if calls:
            breakevens.append(calls[0] + net)
    outlay = -net if net < 0 else max_loss                        # premium paid, or ~margin of a defined-risk spread
    return {"legs": legs, "net_per_unit": net, "debit": net < 0, "lot": lot, "spot": spot,
            "max_loss_per_lot": max_loss * lot, "max_profit_per_lot": None if max_profit is None else max_profit * lot,
            "outlay_per_lot": outlay * lot, "breakevens": breakevens,
            "reward_to_risk": None if max_profit is None or max_loss <= 0 else max_profit / max_loss}


def charges(priced: dict, lots: int) -> float:
    """Dhan brokerage + statutory charges to open and close every leg (each leg is its own order both ways)."""
    from tradingagents.analytics import costs

    qty = lots * priced["lot"]
    total = 0.0
    for leg in priced["legs"]:
        side_in = "buy" if leg["action"] == "BUY" else "sell"
        side_out = "sell" if side_in == "buy" else "buy"
        total += costs.fill_charges(costs.OPTIONS, qty, leg["price"], side_in)
        total += costs.fill_charges(costs.OPTIONS, qty, leg["price"], side_out)   # exit at about the same premium
    return total


def warnings(plan: StrategyPlan, priced: dict | None) -> list[str]:
    """Things the trader should see before acting; the proposal stands but is flagged."""
    out = []
    lo, hi, tgt, stop = (plan.underlying_entry_low, plan.underlying_entry_high, plan.underlying_target,
                         plan.underlying_stop)
    if None not in (lo, hi, tgt, stop):
        mid = (lo + hi) / 2
        if not ((tgt > mid > stop) or (tgt < mid < stop)):
            out.append("The target and stop are not on opposite sides of the entry: treat these levels with care.")
    if priced:
        rr = priced.get("reward_to_risk")
        if rr is not None and rr < 0.5:
            out.append(f"Risking ₹{priced['max_loss_per_lot']:,.0f} to make at most ₹{priced['max_profit_per_lot']:,.0f} "
                       f"per lot: it must work about {1 / (1 + rr):.0%} of the time just to break even.")
        if any(not leg["bid"] or not leg["ask"] for leg in priced["legs"]):
            out.append("A leg has no live bid or ask (market closed or illiquid): priced at the last trade.")
    return out


def recommend(symbol: str, expiry: str | None = None, llm=None) -> dict:
    ctx, ch = build_context(symbol, expiry)
    started = datetime.now()
    plan = (llm or ask_llm)(ctx)
    out = {"symbol": symbol, "expiry": ch["expiry"], "spot": ch["spot"], "lot": ch["lot"],
           "seconds": (datetime.now() - started).seconds, "plan": plan.model_dump(),
           "strategy_text": STRATEGIES[plan.strategy][0], "chain_summary": ch["summary"]}
    problems = check_structure(plan, ch)
    if problems:
        out.update(rejected=problems, priced=None, warnings=[])
        return out
    if plan.strategy != "no_trade":
        priced = price(plan, ch)
        out.update(priced=priced, charges_per_lot=charges(priced, 1))
    out["warnings"] = warnings(plan, out.get("priced"))
    return out


# ---------------------------------------------------------------- background jobs (the LLM takes a minute or two)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def start(symbol: str, expiry: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "symbol": symbol, "started": datetime.now().strftime("%H:%M:%S")}

    def run():
        try:
            result = {"status": "done", "result": recommend(symbol, expiry)}
        except Exception as exc:
            result = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        with _jobs_lock:
            _jobs[job_id].update(result)

    threading.Thread(target=run, daemon=True).start()
    return job_id


def job(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None
