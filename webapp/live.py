"""The Plan tab's live view of the last AI run: the same trades, in the same order, priced again from NSE's chain now.

An AI run takes about a minute and its trades then stay fixed, so the prices on the card age from the moment the run
began. This view changes nothing in the run: no LLM is asked, the ranking, the legs and the index levels (entry zone,
target, stop) stay the run's. Only the code's part is done again, through the same functions a Take uses
(``trade_record.fresh_candidate``): each leg's bid / ask price, the premiums at the target and stop, the money for one
lot. Each trade also gets a status from where the index is now against its own levels:

- ``enter``    inside the entry zone
- ``ran``      past the entry zone towards the target (do not chase)
- ``against``  between the entry zone and the stop
- ``stop``     at or beyond the stop (the idea has failed)
- ``target``   at or beyond the target (the move is done)
- ``unquoted`` a leg has no live bid or ask: the run's prices are kept

Read only: it writes no file and records nothing, so the forward test and the trade record do not see it.
Display only; no status here has been tested for an edge.
"""

from __future__ import annotations


def zone_status(plan: dict, spot: float) -> str | None:
    """Where ``spot`` is against the trade's index levels; None when a level is missing or they are not a
    target and a stop on opposite sides of the entry zone."""
    lo, hi = plan.get("underlying_entry_low"), plan.get("underlying_entry_high")
    tgt, stop = plan.get("underlying_target"), plan.get("underlying_stop")
    if None in (lo, hi, tgt, stop, spot) or not (tgt > hi >= lo > stop or tgt < lo <= hi < stop):
        return None
    up = tgt > stop
    if (spot <= stop) if up else (spot >= stop):
        return "stop"
    if (spot >= tgt) if up else (spot <= tgt):
        return "target"
    if lo <= spot <= hi:
        return "enter"
    return "ran" if (spot > hi) == up else "against"


def view(symbol: str, chain_fn=None) -> dict:
    """The last run of ``symbol`` at NSE's prices now, or ``{"live": False, "why": ...}`` when there is nothing live
    to show: no run, a run from another day, the market closed, the chain unavailable or its quotes too old to trade
    at (the same checks, in the same order, as a Take)."""
    from webapp import option_chain as oc, signals, strategist as st, trade_record as tr

    def off(why: str, **more) -> dict:
        return {"live": False, "symbol": symbol, "why": why} | more

    run = st.latest_run(symbol)
    if not run or not run.get("trades"):
        return off("No AI run with trades for this instrument.")
    if st.run_expired(run):
        return off(tr.MESSAGES["run_expired"])
    if why := tr.entry_allowed():
        return off(why)
    try:
        ch = (chain_fn or oc.chain)(symbol, run["expiry"])
    except Exception as exc:                               # the card keeps the run's prices and says why
        return off(f"NSE chain unavailable: {str(exc)[:160]}")
    now = signals.now_ist()
    age, why = tr._quote_age(ch, now)
    if why:
        return off(why, age_s=age)
    spot, trades = ch["spot"], []
    for c in run["trades"]:
        row = {"rank": c.get("rank"), "status": "unquoted", "priced": None, "levels": None, "charges_per_lot": None}
        if not tr.unquoted_leg(c["plan"], ch):
            fresh = tr.fresh_candidate(c, ch, now.date())
            row.update(status=zone_status(c["plan"], spot), priced=fresh["priced"], levels=fresh["levels"],
                       charges_per_lot=fresh["charges_per_lot"])
        trades.append(row)
    return {"live": True, "symbol": symbol, "run_id": run["run_id"], "expiry": run["expiry"], "spot": spot,
            "spot_at_run": run.get("spot"), "as_of": ch["timestamp"][-8:], "age_s": age, "trades": trades}
