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


DIRECTION = {"long_call": "bullish", "bull_call_spread": "bullish", "bull_put_spread": "bullish",
             "long_put": "bearish", "bear_put_spread": "bearish", "bear_call_spread": "bearish",
             "iron_condor": "neutral"}


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
- Prefer the direction most of the evidence agrees on (daily trend, today's intraday rule, IV vs forecast for
  buying vs selling, room to the target within the expected move, OI walls, FII positioning); the bias must match
  the strategy's direction. Report confidence honestly: high only when most of these agree.
- If ai_analysis (the multi-agent research team's report: price, news, sentiment, fundamentals, debate, risk team)
  is given, weigh it alongside the market data. Where it disagrees with the data, say so in your reasoning; the
  data wins, and a real conflict means lower confidence or no_trade.
- Prefer no_trade when signals conflict, the trend fights the setup, or the reward does not justify the risk.
  No strategy in this system has a proven edge; say so plainly where relevant.
- Be specific to this instrument and these numbers. Plain English, no hype."""


# (context key, report name in webapp.ai.REPORTS, characters kept): the decision in full, the rest as excerpts.
ANALYSIS_EXCERPTS = [("final_decision", "Final decision", 3000), ("trader_plan", "Trader's plan", 1500),
                     ("price_and_indicators", "Price & indicators", 1500), ("news", "News", 1200),
                     ("social_sentiment", "Social sentiment", 800), ("fundamentals", "Fundamentals", 800)]


def _num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 2)


def build_context(symbol: str, expiry: str | None = None, analysis: dict | None = None) -> tuple[dict, dict]:
    """(context for the LLM, the option chain used). ``analysis``: a finished complete AI analysis
    (``webapp.analysis``) to build the strategy from; otherwise the morning's AI view, when there is one."""
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
        ctx["trend"] = {k: m.get(k) for k in ("label", "tone", "explain", "returns", "averages", "pos_52w", "low_52w", "high_52w",
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
    if analysis:
        r = analysis.get("reports") or {}
        ctx["ai_analysis"] = {"rating": analysis.get("rating"), "finished_at": analysis.get("finished"),
                              **{k: (r.get(name) or "")[:n] for k, name, n in ANALYSIS_EXCERPTS if r.get(name)}}
    else:
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


def ask_llm(ctx: dict, feedback: list[str] | None = None) -> StrategyPlan:
    from tradingagents.default_config import build_default_config
    from tradingagents.llm_clients import create_tier_client

    llm = create_tier_client(build_default_config(), "deep").get_llm().with_structured_output(StrategyPlan)
    user = f"The app prices the legs and shows per-lot figures; do not size.\n\nDATA:\n{json.dumps(ctx, default=str)}"
    if feedback:                                       # second attempt: the app's checks refused the first answer
        user += ("\n\nYOUR PREVIOUS ANSWER WAS REFUSED BY THE APP'S CHECKS: " + "; ".join(feedback) +
                 ". Answer again: the bias must match the strategy's direction and the legs must form the named "
                 "strategy exactly. Choose no_trade if no consistent setup exists.")
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
              and puts[-1].strike <= calls[0].strike)             # equal: an iron butterfly
        if not ok:
            problems.append("an iron condor is buy put < sell put <= sell call < buy call")
    elif [(x.action, x.option_type) for x in sorted(legs, key=lambda x: x.strike)] != shape:
        problems.append(f"the legs do not form a {plan.strategy.replace('_', ' ')}")
    # No naked short: every sold option is paired with a bought option of the same type and expiry. Any strike
    # caps the risk — a bought put above a sold put (bear put spread) as much as one below (bull put spread).
    for kind in ("CE", "PE"):
        sold = [x for x in legs if x.option_type == kind and x.action == "SELL"]
        bought = [x for x in legs if x.option_type == kind and x.action == "BUY"]
        for leg in sold[len(bought):]:
            problems.append(f"the sold {leg.strike:g} {leg.option_type} has no protective bought option")
    direction = DIRECTION.get(plan.strategy)
    if direction and plan.bias in ("bullish", "bearish", "neutral") and plan.bias != direction:
        problems.append(f"the bias is {plan.bias} but a {plan.strategy.replace('_', ' ')} is a {direction} trade")
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
                     "chg": q.get("chg"), "bid": q["bid"], "ask": q["ask"], "bid_qty": q.get("bid_qty"),
                     "ask_qty": q.get("ask_qty"), "total_buy_qty": q.get("total_buy_qty"),
                     "total_sell_qty": q.get("total_sell_qty"), "iv": q["iv"], "oi": q["oi"], "id": q.get("id")})
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


def _bs(spot: float, strike: float, years: float, iv: float, kind: str, rate: float = 0.065) -> float:
    """Black-Scholes value of a European option (NSE index options are European)."""
    if years <= 0 or iv <= 0:
        return max(0.0, spot - strike) if kind == "CE" else max(0.0, strike - spot)
    d1 = (math.log(spot / strike) + (rate + iv * iv / 2) * years) / (iv * math.sqrt(years))
    d2 = d1 - iv * math.sqrt(years)
    n = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))  # noqa: E731
    if kind == "CE":
        return spot * n(d1) - strike * math.exp(-rate * years) * n(d2)
    return strike * math.exp(-rate * years) * n(-d2) - spot * n(-d1)


def _tick(x: float) -> float:
    return max(0.05, round(round(x / 0.05) * 0.05, 2))


def trade_levels(plan: StrategyPlan, priced: dict, chain: dict, days_to_expiry: float | None) -> dict | None:
    """What each leg's premium should be when the index reaches the AI's target and stop — the numbers to type into
    the broker's target / stop-loss boxes — and the profit or loss per lot there.

    Each premium is moved from its live price by the Black-Scholes change between today's index level and the
    target / stop (same implied vol, same day): an estimate for a move today; closer to expiry the option moves more.
    """
    tgt, stop = plan.underlying_target, plan.underlying_stop
    if tgt is None or stop is None or not priced:
        return None
    spot, lot = chain["spot"], priced["lot"]
    years = max(days_to_expiry or 1, 0.5) / 365
    atm_iv = (chain["summary"].get("atm_iv") or 15) / 100
    legs, pnl_t, pnl_s = [], 0.0, 0.0
    for leg in priced["legs"]:
        iv = (leg["iv"] or 0) / 100 or atm_iv
        now = _bs(spot, leg["strike"], years, iv, leg["type"])
        at = {k: _tick(leg["price"] + _bs(lvl, leg["strike"], years, iv, leg["type"]) - now) for k, lvl in
              (("target", tgt), ("stop", stop))}
        sgn = 1 if leg["action"] == "BUY" else -1                 # a bought option gains when its premium rises
        legs.append({**leg, "premium_at_target": at["target"], "premium_at_stop": at["stop"],
                     "pnl_target_per_lot": sgn * (at["target"] - leg["price"]) * lot,
                     "pnl_stop_per_lot": sgn * (at["stop"] - leg["price"]) * lot})
        pnl_t += legs[-1]["pnl_target_per_lot"]
        pnl_s += legs[-1]["pnl_stop_per_lot"]
    net_now = abs(priced["net_per_unit"])
    value = {k: abs(sum((1 if x["action"] == "BUY" else -1) * x[f"premium_at_{k}"] for x in legs)) for k in ("target", "stop")}
    return {"legs": legs, "pnl_target_per_lot": pnl_t, "pnl_stop_per_lot": pnl_s, "assumed_days": years * 365,
            "spread": None if len(legs) == 1 else {"now": net_now, "at_target": value["target"], "at_stop": value["stop"],
                                                   "debit": priced["debit"]}}


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


def evidence(plan: StrategyPlan, ctx: dict, priced: dict | None) -> dict | None:
    """Pulse's own score (0-100) of how much of the data backs the trade's direction and structure, independent
    of the AI's self-reported confidence. Each check agrees (full weight), is neutral (half) or disagrees (none)."""
    direction = DIRECTION.get(plan.strategy)
    if not direction or not priced:
        return None
    spot = ctx.get("spot")
    checks = []

    def add(name, weight, verdict, why):
        checks.append({"name": name, "weight": weight, "verdict": verdict, "why": why})

    tone = (ctx.get("trend") or {}).get("tone")
    want = {"bullish": "up", "bearish": "down", "neutral": "flat"}[direction]
    label = (ctx.get("trend") or {}).get("label") or "unknown"
    add("Daily trend", 25, "agree" if tone == want else "neutral" if tone in (None, "flat") or want == "flat" else "against",
        f"{label} (20/50/200-day averages)")
    side = (ctx.get("intraday_rule") or {}).get("side")
    rule = {"BUY": "bullish", "SELL": "bearish"}.get(side)
    add("Today's intraday rule", 15, "neutral" if rule is None or direction == "neutral" else "agree" if rule == direction else "against",
        {"BUY": "says buy", "SELL": "says sell"}.get(side, "no clean setup yet (wait)"))
    iv = ctx.get("implied_vol_vs_forecast") or {}
    gap, pct = iv.get("minus_garch21"), iv.get("percentile_1y")
    rich = (gap is not None and gap > 0.01) or (pct is not None and pct > 0.7)
    cheap = (gap is not None and gap < -0.01) or (pct is not None and pct < 0.3)
    credit = not priced["debit"]
    add("Option prices vs the trade", 20,
        "agree" if (credit and rich) or (not credit and cheap) else "against" if (credit and cheap) or (not credit and rich) else "neutral",
        f"options look {'expensive' if rich else 'cheap' if cheap else 'fairly priced'} vs the volatility forecast; "
        f"this trade {'sells' if credit else 'buys'} premium")
    em = ctx.get("expected_move") or {}
    day = em.get("day_pct")
    days = max(ctx.get("days_to_expiry") or 1, 1)
    if day and spot and plan.underlying_target is not None:
        reach = spot * day * math.sqrt(days)
        dist = abs(plan.underlying_target - spot)
        add("Room to the target", 20, "agree" if dist <= reach else "against" if dist > 2 * reach else "neutral",
            f"target {dist:,.0f} points away; a typical move to expiry is about {reach:,.0f}")
    else:
        add("Room to the target", 20, "neutral", "no expected-move forecast for this instrument")
    sm = (ctx.get("option_chain") or {}).get("summary") or {}
    res, sup = sm.get("resistance"), sm.get("support")
    if spot and res and sup:
        ok = {"bearish": spot < res, "bullish": spot > sup, "neutral": sup < spot < res}[direction]
        add("Option walls", 10, "agree" if ok else "against",
            f"call wall {res:,.0f} above, put wall {sup:,.0f} below, price {spot:,.0f}")
    fii = (ctx.get("fii_index_futures_long_share") or {}).get("value")
    if fii is not None:
        lean = "bearish" if fii < 0.35 else "bullish" if fii > 0.65 else "neutral"
        add("Foreign investors (FII)", 10, "agree" if lean == direction else "neutral" if lean == "neutral" else "against",
            f"{fii:.0%} of their index futures are long")
    total = sum(c["weight"] for c in checks)
    got = sum(c["weight"] * {"agree": 1, "neutral": 0.5, "against": 0}[c["verdict"]] for c in checks)
    score = round(got / total * 100) if total else None
    return {"score": score, "label": "Strong" if score >= 70 else "Moderate" if score >= 45 else "Weak",
            "checks": checks}


def recommend(symbol: str, expiry: str | None = None, llm=None, analysis: dict | None = None) -> dict:
    ctx, ch = build_context(symbol, expiry, analysis)
    started = datetime.now()
    ask = llm or ask_llm
    plan = ask(ctx)
    problems = check_structure(plan, ch)
    retried = None
    if problems:                                       # one more try, told exactly what was wrong
        retried = problems
        plan = ask(ctx, problems)
        problems = check_structure(plan, ch)
    out = {"symbol": symbol, "expiry": ch["expiry"], "spot": ch["spot"], "lot": ch["lot"],
           "seconds": (datetime.now() - started).seconds, "plan": plan.model_dump(),
           "strategy_text": STRATEGIES[plan.strategy][0], "chain_summary": ch["summary"], "retried": retried,
           "asked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
           "from_analysis": {"rating": analysis.get("rating"), "finished": analysis.get("finished")} if analysis else None}
    if problems:
        out.update(rejected=problems, priced=None, warnings=[])
        return out
    if plan.strategy != "no_trade":
        priced = price(plan, ch)
        out.update(priced=priced, charges_per_lot=charges(priced, 1),
                   levels=trade_levels(plan, priced, ch, ctx.get("days_to_expiry")))
    out["warnings"] = warnings(plan, out.get("priced"))
    out["evidence"] = evidence(plan, ctx, out.get("priced"))
    return out


# ---------------------------------------------------------------- Pulse trade ranking (rules, no LLM)

def _index_levels(direction: str, spot: float, reach: float) -> dict:
    """Index entry zone, target and stop for a directional trade: the target at 80% of a typical move to expiry,
    the stop at 40% against (2 : 1 on the index), rounded to 5 points."""
    r5 = lambda x: round(x / 5) * 5  # noqa: E731
    sgn = 1 if direction == "bullish" else -1
    return {"underlying_entry_low": r5(spot - 0.1 * reach), "underlying_entry_high": r5(spot + 0.1 * reach),
            "underlying_target": r5(spot + sgn * 0.8 * reach), "underlying_stop": r5(spot - sgn * 0.4 * reach)}


def _structures(direction: str, strikes: list[float], atm: float) -> list[tuple[str, list[tuple[str, str, float]]]]:
    """Candidate structures from the chain's strikes: single options at the money and 1-2 steps out, debit spreads
    2 and 4 steps wide, credit spreads 1-2 steps out of the money and 2 steps wide."""
    i = strikes.index(atm)
    at = lambda k: strikes[k] if 0 <= k < len(strikes) else None  # noqa: E731
    out = []
    if direction == "bullish":
        for o in (0, 1, 2):
            if at(i + o):
                out.append(("long_call", [("BUY", "CE", at(i + o))]))
        for lo, w in ((0, 2), (0, 4), (1, 2)):
            if at(i + lo) and at(i + lo + w):
                out.append(("bull_call_spread", [("BUY", "CE", at(i + lo)), ("SELL", "CE", at(i + lo + w))]))
        for o in (1, 2):
            if at(i - o) and at(i - o - 2):
                out.append(("bull_put_spread", [("BUY", "PE", at(i - o - 2)), ("SELL", "PE", at(i - o))]))
    else:
        for o in (0, 1, 2):
            if at(i - o):
                out.append(("long_put", [("BUY", "PE", at(i - o))]))
        for hi, w in ((0, 2), (0, 4), (1, 2)):
            if at(i - hi) and at(i - hi - w):
                out.append(("bear_put_spread", [("SELL", "PE", at(i - hi - w)), ("BUY", "PE", at(i - hi))]))
        for o in (1, 2):
            if at(i + o) and at(i + o + 2):
                out.append(("bear_call_spread", [("SELL", "CE", at(i + o)), ("BUY", "CE", at(i + o + 2))]))
    return out


def rank(symbol: str, expiry: str | None = None, top: int = 8, built=None) -> dict:
    """Every candidate trade for both directions, priced at the bid / ask with index and premium levels, scored by
    the evidence and ranked best first. Ties go to the better profit-to-loss ratio at the levels."""
    ctx, ch = built or build_context(symbol, expiry)
    spot, days = ch["spot"], max(ctx.get("days_to_expiry") or 1, 1)
    day = (ctx.get("expected_move") or {}).get("day_pct") or ((ctx.get("trend") or {}).get("daily_move_pct") or 1) / 100
    reach = spot * day * math.sqrt(days)
    strikes = [r["strike"] for r in ch["rows"]]
    out = []
    for direction in ("bullish", "bearish"):
        lv_index = _index_levels(direction, spot, reach)
        for strategy, legs in _structures(direction, strikes, ch["atm"]):
            plan = StrategyPlan(
                market_read="", bias=direction, strategy=strategy, legs=[Leg(action=a, option_type=t, strike=k) for a, t, k in legs],
                buy_or_sell_reasoning="", strike_reasoning="", exit_plan="", confidence="medium", **lv_index)
            if check_structure(plan, ch):
                continue
            try:
                priced = price(plan, ch)
            except (KeyError, TypeError):
                continue
            if any(not x["bid"] or not x["ask"] for x in priced["legs"]) or priced["max_loss_per_lot"] <= 0:
                continue                                            # no live two-sided quote: not tradable now
            lv = trade_levels(plan, priced, ch, ctx.get("days_to_expiry"))
            if not lv or lv["pnl_target_per_lot"] <= 0 or lv["pnl_stop_per_lot"] >= 0:
                continue
            ev = evidence(plan, ctx, priced)
            ratio = lv["pnl_target_per_lot"] / -lv["pnl_stop_per_lot"]
            word = "rises" if direction == "bullish" else "falls"
            plan.market_read = (f"Pulse rule: a {direction} trade, ranked by how much of the data agrees "
                                f"(score {ev['score']}/100). Target at 80% of a typical move to expiry "
                                f"(about {reach:,.0f} points), stop at 40% against.")
            plan.strike_reasoning = ", ".join(f"{a.lower()} {k:,.0f} {t} ({abs(k - spot) / (strikes[1] - strikes[0]):.0f} "
                                              f"strike{'s' if abs(k - spot) >= 2 * (strikes[1] - strikes[0]) else ''} "
                                              f"{'out of' if (t == 'CE') == (k > spot) else 'in'} the money)"
                                              for a, t, k in legs) + "."
            plan.buy_or_sell_reasoning = next(c["why"] for c in ev["checks"] if c["name"] == "Option prices vs the trade") + "."
            plan.exit_plan = (f"Book profit if the index {word} to {plan.underlying_target:,.0f}; exit if it reaches "
                              f"{plan.underlying_stop:,.0f}." + (
                                  "" if len(legs) == 1 else
                                  " In Dhan: Super order (target + stop loss) on the SELL leg only; sell the BUY leg"
                                  " right after it fills." if strategy in ("bear_call_spread", "bull_put_spread") else
                                  " Close both legs together by hand (buy back the SELL leg first).") +
                              " On expiry day close by 15:15.")
            out.append({"symbol": symbol, "expiry": ch["expiry"], "spot": spot, "lot": ch["lot"],
                        "plan": plan.model_dump(), "strategy_text": STRATEGIES[strategy][0], "priced": priced,
                        "levels": lv, "evidence": ev, "charges_per_lot": charges(priced, 1),
                        "warnings": warnings(plan, priced), "ratio": ratio, "chain_summary": ch["summary"],
                        "source": "pulse", "seconds": 0})
    out.sort(key=lambda c: (c["evidence"]["score"], c["ratio"]), reverse=True)
    for n, c in enumerate(out, 1):
        c["rank"] = n
    return {"symbol": symbol, "expiry": ch["expiry"], "spot": spot, "reach": reach, "candidates": out[:top],
            "considered": len(out), "built_at": datetime.now().strftime("%H:%M:%S")}


# ---------------------------------------------------------------- background jobs (the LLM takes a minute or two)

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def todays_analysis(symbol: str) -> dict | None:
    """Today's finished complete AI analysis of ``symbol`` (Plan tab), so "Ask again" builds on it too."""
    from webapp import analysis

    a = analysis.load(symbol)
    return a if a and a.get("status") == "done" and str(a.get("finished", "")).startswith(date.today().isoformat()) else None


def start(symbol: str, expiry: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "symbol": symbol, "started": datetime.now().strftime("%H:%M:%S")}

    def run():
        try:
            res = recommend(symbol, expiry, analysis=todays_analysis(symbol))
            if res.get("priced"):                      # every valid suggestion goes into the AI track record
                try:
                    from webapp import trade_record
                    res["ai_record"] = trade_record.take(res, source="ai")["id"]
                except Exception:
                    pass
            result = {"status": "done", "result": res}
        except Exception as exc:
            result = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        with _jobs_lock:
            _jobs[job_id].update(result)

    threading.Thread(target=run, daemon=True).start()
    return job_id


def job(job_id: str) -> dict | None:
    with _jobs_lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None
