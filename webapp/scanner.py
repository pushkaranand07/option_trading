"""The Scanner tab: which instrument to trade options in today, across the indices and the header's F&O stocks.

Three steps, cheapest first, so the slow parts run on a few names only:

1. **Screen (code, every instrument, seconds).** Today's tape (``signals.today_tape``: price vs VWAP, EMA 9 vs 21, price
   vs today's open), how unusual today's move from the open is against the instrument's typical daily move (``move_z``),
   the daily trend as of yesterday's close, and the option the user could buy in the tape's direction: the strike
   nearest the money (up to two steps out of the money) whose ask for one lot fits the budget, with a live two-sided
   quote. A mixed tape or no affordable, quoted option gives no score.
2. **Build (code, the top ``FINALISTS``).** The full trade the Plan tab would price: ``strategist.build_context`` and
   ``strategist.rank``, the single bought option at that strike, with its index entry zone, target, stop and the premiums
   there.
3. **Rank (one LLM call).** The AI orders the finalists by the whole picture and may leave weak ones out. It cannot
   change a direction, a strike or a price. Index research from today (the Complete analysis or the 8:30 view) is passed
   as news and risk context; stocks have none.

Display only: nothing is recorded in the trade record or the forward test, and no score here has been tested for an
edge. A Muhurat day gives no picks (the user does not trade it).
"""

from __future__ import annotations

import json
import logging
import math
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

INDICES = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY")    # SENSEX trades on BSE: no NSE chain
FINALISTS = 5
MAX_OTM_STEPS = 2
WORKERS = 4                                                   # NSE is asked for one chain per instrument
TREND_WEIGHT = {"agrees": 1.25, "flat": 1.0, "against": 0.75}


def universe() -> list[str]:
    from webapp import market_data as md

    return list(INDICES) + [s["symbol"] for s in md.fo_stocks() if s["symbol"] not in INDICES]


def pick_option(ch: dict, direction: str, budget: float) -> tuple[dict | None, str | None]:
    """(the option to buy in ``direction`` that one lot of fits ``budget``, or None and why). The strike nearest the
    money first, then up to MAX_OTM_STEPS steps out of the money; each needs a live bid and ask."""
    kind = "ce" if direction == "up" else "pe"
    rows = ch["rows"]
    strikes = [r["strike"] for r in rows]
    if ch.get("atm") not in strikes:
        return None, "no at-the-money strike on the chain"
    i, step = strikes.index(ch["atm"]), 1 if kind == "ce" else -1
    lot, first_cost = ch["lot"], None
    for n in range(MAX_OTM_STEPS + 1):
        j = i + step * n
        if not 0 <= j < len(rows):
            break
        q = rows[j][kind]
        if not q or not q.get("bid") or not q.get("ask"):
            continue
        cost = q["ask"] * lot
        first_cost = first_cost or cost
        if cost <= budget:
            mid = (q["ask"] + q["bid"]) / 2
            return {"strike": rows[j]["strike"], "type": kind.upper(), "ask": q["ask"], "bid": q["bid"], "lot": lot,
                    "cost": round(cost, 2), "spread_pct": round((q["ask"] - q["bid"]) / mid * 100, 2), "steps_out": n,
                    "iv": q.get("iv"), "oi": q.get("oi")}, None
    if first_cost is None:
        return None, "no live bid / ask near the money"
    return None, f"1 lot costs ₹{first_cost:,.0f} or more (budget ₹{budget:,.0f})"


def _move_z(tape: dict, daily) -> tuple[float | None, float | None, int]:
    """(today's move from the open in %, that move in units of the typical daily move, the daily trend at yesterday's
    close: +1 up, -1 down, 0 sideways)."""
    from webapp import signals

    past = daily[daily.index.date < datetime.strptime(tape["as_of_day"], "%Y-%m-%d").date()] if tape.get("as_of_day") else daily
    typical = past["close"].pct_change().dropna().tail(20).std()
    trend = int(signals.daily_trend(past).iloc[-1]) if len(past) else 0
    if not tape.get("price") or not tape.get("day_open"):
        return None, None, trend
    move = tape["price"] / tape["day_open"] - 1
    z = move / typical if typical and not math.isnan(typical) else None
    return round(move * 100, 2), None if z is None else round(z, 2), trend


def screen(symbol: str, budget: float, chain_fn=None, candles_fn=None) -> dict:
    """Step 1 for one instrument: its tape, move, trend, the affordable option and a score (0: not a candidate)."""
    from webapp import market_data as md, option_chain as oc, signals

    row = {"symbol": symbol, "kind": "INDEX" if symbol in md.INDICES else "STOCK", "score": 0.0}
    try:
        bars, _ = (candles_fn or md.candles)(symbol, "5m")
        daily, _ = (candles_fn or md.candles)(symbol, "1D")
        tape = signals.today_tape(bars)
        tape["as_of_day"] = str(bars.index[-1].date()) if bars is not None and len(bars) else None
        move, z, trend = _move_z(tape, daily)
        ch = (chain_fn or oc.chain)(symbol)
    except Exception as exc:
        return row | {"why": f"data unavailable: {str(exc)[:160]}"}
    direction = tape["direction"]
    side = {"up": 1, "down": -1}.get(direction, 0)
    agreement = "flat" if trend == 0 else "agrees" if trend == side else "against"
    row |= {"tape": direction, "tape_as_of": tape.get("as_of"), "price": tape.get("price"), "move_pct": move, "move_z": z,
            "trend": {1: "up", -1: "down", 0: "sideways"}[trend], "trend_vs_tape": agreement if side else None,
            "expiry": ch["expiry"], "lot": ch["lot"], "pcr": (ch.get("summary") or {}).get("pcr"),
            "call_wall": (ch.get("summary") or {}).get("resistance"), "put_wall": (ch.get("summary") or {}).get("support"),
            "atm_iv": (ch.get("summary") or {}).get("atm_iv"), "chain_as_of": ch.get("timestamp")}
    if not side:
        return row | {"why": "tape mixed: no clear direction today"}
    option, why = pick_option(ch, direction, budget)
    row["option"] = option
    if not option:
        return row | {"why": why}
    if z is None:
        return row | {"why": "no typical daily move to compare today's with"}
    # The move must go the tape's way (it does when the tape is clear: price is past the open in that direction).
    row["score"] = round(abs(z) * TREND_WEIGHT[agreement], 3)
    return row | {"why": None}


def build_trade(row: dict, budget: float) -> dict | None:
    """Step 2: the single bought option at the screened strike as the Plan tab prices it, with index levels and the
    premiums at the target and stop (``strategist.rank``); None when rank keeps no such trade."""
    from webapp import strategist as st

    built = st.build_context(row["symbol"], row["expiry"])
    want = "long_call" if row["tape"] == "up" else "long_put"
    cands = [c for c in st.rank(row["symbol"], row["expiry"], top=10 ** 6, built=built)["candidates"]
             if c["plan"]["strategy"] == want and c["priced"]["outlay_per_lot"] <= budget]
    same = [c for c in cands if c["priced"]["legs"][0]["strike"] == row["option"]["strike"]]
    pick = (same or cands or [None])[0]
    return json.loads(json.dumps(pick, default=str)) if pick else None


class ScanPick(BaseModel):
    symbol: str = Field(description="the finalist's symbol, exactly as listed")
    why: str = Field(description="1-2 plain sentences: why this instrument today, tied to its numbers")
    confidence: Literal["low", "medium", "high"]


class ScanAnswer(BaseModel):
    market_read: str = Field(description="2-4 plain sentences on today's market across the finalists")
    picks: list[ScanPick] = Field(description="the finalists worth trading today, strongest first; leave out weak ones")
    left_out: str = Field(description="one sentence on which finalists were left out and why; empty if none")


SCAN_SYSTEM = """You are a careful options trader for Indian markets (NSE). The app screened the indices and liquid F&O
stocks and gives you a few finalists. For each: today's tape (price vs VWAP, EMA 9 vs EMA 21, price vs today's open), how
big today's move from the open is against its typical daily move (move_z), the daily trend as of yesterday's close, the
option chain summary (PCR, call and put walls, ATM implied vol), and ONE trade the app built and priced: a single bought
call (tape up) or put (tape down) that fits the user's budget for one lot, with its index entry zone, target and stop
and the option's premium at each. You cannot change the direction, the strike or any price.

Order the finalists strongest first by how well the whole picture supports a move in the tape's direction that can reach
the target: a clear tape with the daily trend, room to the next wall in that direction, implied vol not rich, a tight
bid-ask spread, and for indices today's research (a multi-week view: use it for news and event risk, never by itself to
bet against the tape). Leave out finalists you would not trade today and say why. Report confidence honestly: high only
when most of the evidence agrees. Nothing here has a proven edge. Plain English, no hype."""


def ask_scan_llm(finalists: list[dict]) -> ScanAnswer:
    from tradingagents.default_config import build_default_config
    from tradingagents.llm_clients import create_tier_client

    llm = create_tier_client(build_default_config(), "deep").get_llm().with_structured_output(ScanAnswer)
    return llm.invoke([("system", SCAN_SYSTEM), ("user", "FINALISTS:\n" + json.dumps(finalists, default=str))])


def _for_ai(row: dict) -> dict:
    """What the AI sees of a finalist."""
    from webapp import strategist as st

    t, out = row["trade"], {k: row.get(k) for k in ("symbol", "kind", "tape", "tape_as_of", "price", "move_pct", "move_z",
                                                     "trend", "pcr", "call_wall", "put_wall", "atm_iv", "expiry")}
    leg, p = t["levels"]["legs"][0], t["plan"]
    out["trade"] = {"buy": f"{leg['strike']:g} {leg['type']}", "ask": leg["price"], "lot": t["priced"]["lot"],
                    "cost_one_lot": round(t["priced"]["outlay_per_lot"]), "spread_pct": row["option"]["spread_pct"],
                    "index_entry_zone": [p["underlying_entry_low"], p["underlying_entry_high"]], "index_target": p["underlying_target"],
                    "index_stop": p["underlying_stop"], "premium_at_target": leg["premium_at_target"],
                    "premium_at_stop": leg["premium_at_stop"]}
    if row["kind"] == "INDEX" and (r := st.today_research(row["symbol"])):
        out["research_today"] = {"rating": r.get("rating"), "decision_excerpt": (r.get("decision") or "")[:800]}
    return out


def scan(budget: float, symbols: list[str] | None = None, llm=None, chain_fn=None, candles_fn=None, build_fn=None,
         progress=None) -> dict:
    """Screen every instrument, build the top FINALISTS, and let the AI order them. Returns the whole scan."""
    from webapp import signals, trade_record

    say = progress or (lambda stage: None)
    started = signals.now_ist()
    symbols = symbols or universe()
    say("screen")
    with ThreadPoolExecutor(WORKERS) as pool:
        rows = list(pool.map(lambda s: screen(s, budget, chain_fn, candles_fn), symbols))
    rows.sort(key=lambda r: r["score"], reverse=True)
    out = {"asked_at": started.strftime("%Y-%m-%d %H:%M"), "budget": budget, "scanned": rows, "picks": [],
           "market_closed": trade_record.entry_allowed() is not None, "market_read": "", "left_out": ""}
    if started.date() in getattr(signals.nse_calendar(), "muhurat_days", set()):
        return out | {"muhurat": True, "market_read": "Muhurat day: no picks (you don't trade it)."}
    say("build")
    finalists = []
    for row in [r for r in rows if r["score"] > 0][:FINALISTS]:
        try:
            row["trade"] = (build_fn or build_trade)(row, budget)
        except Exception as exc:
            row["trade"], row["why"] = None, f"could not build the trade: {str(exc)[:160]}"
        if row["trade"]:
            finalists.append(row)
        elif not row.get("why"):
            row["why"] = "the Plan tab's rules keep no such trade (target or stop not on the right side)"
    if not finalists:
        return out | {"market_read": "No instrument has a clear tape and an affordable, quoted option right now."}
    say("ai")
    by_symbol = {r["symbol"]: r for r in finalists}
    try:
        answer = (llm or ask_scan_llm)([_for_ai(r) for r in finalists])
        seen = set()
        for p in answer.picks:
            if p.symbol in by_symbol and p.symbol not in seen:            # an unknown or repeated symbol is dropped
                seen.add(p.symbol)
                out["picks"].append({"symbol": p.symbol, "why": p.why, "confidence": p.confidence, "rank": len(out["picks"]) + 1,
                                     "row": by_symbol[p.symbol]})
        out |= {"market_read": answer.market_read, "left_out": answer.left_out}
    except Exception as exc:                                              # the screen's order stands, said plainly
        logger.exception("the scan's AI step failed")
        out["ai_error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        out["picks"] = [{"symbol": r["symbol"], "why": None, "confidence": None, "rank": n, "row": r} for n, r in enumerate(finalists, 1)]
    out["seconds"] = (signals.now_ist() - started).seconds
    return out


# ---------------------------------------------------------------- the last scan, and background jobs

def _scan_file():
    from webapp import strategist as st

    return st._runs_dir() / "scan" / "latest.json"


def save(res: dict) -> None:
    f = _scan_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(res, default=str), encoding="utf-8")


def latest() -> dict | None:
    f = _scan_file()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def start(budget: float) -> str:
    """Run a scan in the background (about a minute and a half); poll ``job``."""
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        if any(j["status"] == "running" for j in _jobs.values()):
            return next(k for k, j in _jobs.items() if j["status"] == "running")      # one scan at a time
        _jobs[job_id] = {"status": "running", "stage": "screen", "started": datetime.now().strftime("%H:%M:%S")}

    def stage(name):
        with _lock:
            _jobs[job_id]["stage"] = name

    def run():
        try:
            res = scan(budget, progress=stage)
            try:
                save(res)
            except Exception:
                logger.exception("the scan was not saved")
            result = {"status": "done", "result": res}
        except Exception as exc:
            logger.exception("the scan failed")
            result = {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:400]}"}
        with _lock:
            _jobs[job_id].update(result)

    threading.Thread(target=run, daemon=True).start()
    return job_id


def job(job_id: str) -> dict | None:
    with _lock:
        return dict(_jobs[job_id]) if job_id in _jobs else None
