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

import contextlib
import hashlib
import json
import logging
import threading
import uuid
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "reports" / "trade_record" / "trades.json"
_lock = threading.Lock()


logger = logging.getLogger(__name__)
from webapp import build_info  # noqa: E402  (the commit and start time each new row records)

# Every user-facing message of the trade record, in one place (Hinglish and English, as shown). Tests assert parts
# of these texts, so change them only on purpose. Templates are filled with str.format.
MESSAGES = {
    # the session gates
    "market_closed": "Market band hai: abhi ke prices pe asli order nahi lag sakta. 9:15 ke baad karna.",
    "exit_market_closed": ("Market band hai: band karne ka asli price abhi nahi hai. 9:15 ke baad band karna; "
                           "expiry ke baad trade expiry value pe band hota hai."),
    "run_expired": "Yeh run expired hai (kisi aur din ka): uske prices aaj ke nahi. Analysis dobara chala, phir Take kar.",
    # why a chain's quotes cannot be traded at now
    "quotes_no_timestamp": "the chain has no timestamp, so its quotes may be old",
    "quotes_bad_timestamp": "the chain's timestamp {ts!r} could not be read",
    "quotes_not_today": "the quotes are from {day}, not today",
    "quotes_clock_behind": "NSE's time ({nse_time}) is {ahead} s ahead of this computer's clock: check the clock",
    "quotes_too_old": "the quotes are {age} s old (limit {limit} s)",
    # a Take refused
    "run_not_on_file": "This run is not on file: run the analysis again.",
    "no_such_candidate": "This run has no trade #{n}.",
    "prices_unavailable_take": "Live prices unavailable ({error}): not taken. Try again in a moment.",
    "nse_refused": "NSE: {why}. Not taken; try again in a moment.",
    "outside_entry_zone": "{symbol} is at {spot:,.2f}, outside this trade's entry zone {lo:,.0f}-{hi:,.0f}: not taken.",
    "leg_unquoted": "{strike:,.0f} {type} has no live bid / ask right now: not taken.",
    "no_trade_in_suggestion": "There is no trade to take in this suggestion.",
    "bet_exists": ("Is disha ({direction}) ka ek {symbol} bet pehle se chal raha hai "
                   "(bet {bet}, shuru {started}). Isi bet mein ek aur trade jodna hai?"),
    # marking and closing
    "prices_unavailable": "Live prices unavailable: {error}",
    "unknown_trade": "Unknown trade.",
    "already_closed": "This trade is already closed.",
    "leg_no_price": "A leg has no live price; try again in a moment.",
    # close reasons (stored on the row and shown on the page)
    "reason_reached": "{kind} reached",
    "reason_range_broken": "range broken",
    "reason_expired": "expired",
    "reason_by_you": "closed by you",
    "range_bug_note": ("reopened 2026-11-04: it had been closed by a bug that read this range trade's single index target / stop "
                       "as a directional trade's"),
    # events.log
    "event_exit_pending": "exit pending: reached its {hit} but has no quote for {legs}",
    "event_removed": "removed from the record by you",
    # the trade record file (audit H1)
    "store_damaged": ("The trade record file trades.json is damaged and cannot be read ({why}). A copy was saved as {copy}. "
                      "Nothing will be written to the trade record until the file is fixed or restored."),
    "store_unreadable": ("The trade record file trades.json cannot be opened ({why}). Nothing will be written to the trade "
                         "record until it can be read again."),
    # the v2 link beside an AI #1 row
    "v2_before_start": "before v{version} started ({first})",
    "v2_nothing": "v{version} registered nothing that day",
    "v2_counted_this": "v{version} counted this trade",
    "v2_counted_other": "v{version} counted a different trade that day",
    "v2_recorded": "v{version} recorded {outcome} that day",
}


def _event(what: str, t: dict, why: str = "", level: int = logging.INFO) -> None:
    """One line in events.log beside the trade record (and the server log): when, which row, what happened, why.
    A failure to write it is logged as a warning and never stops the trade itself."""
    line = (f"{_clock():%Y-%m-%d %H:%M:%S} {t.get('id')} {t.get('source', 'you')} {what} {t.get('strategy')} "
            f"{t.get('symbol')} {t.get('expiry')}" + (f" | {why}" if why else ""))
    logger.log(level, line)
    try:
        path = STORE.parent / "events.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as exc:
        logger.warning("events.log not written (%s): %s", exc, line)


class TradeError(Exception):
    def __init__(self, message: str = "", details: dict | None = None):
        super().__init__(message)
        self.details = details or {}      # what was known when it was refused (index at the Take, in the zone or not)


class BetExists(TradeError):
    """Your Take would add to a bet already running in the same direction: the page asks first (nothing written)."""


def _market_open(at: datetime | None = None) -> bool:
    """NSE's regular session, now or at the moment ``at``: the one place the trade record asks. Outside it the chain
    shows the last prices (NSE keeps refreshing them until about 15:40), which no order could get: no trade is entered,
    closed or settled at them, except at expiry, and a row entered then is not counted."""
    from webapp import signals

    return signals.market_open(at)


MAX_QUOTE_AGE = 120              # seconds: an older chain snapshot is not a price you could trade at now (user's choice,
                                 # 2026-11-05: at 60 s NSE's ~45 s refresh plus the cache refused most Takes, e.g. 78 s, 83 s)
MAX_CLOCK_AHEAD = 30             # seconds NSE's stamp may run ahead of this computer's clock


def _quote_age(ch: dict, now: datetime) -> tuple[int | None, str | None]:
    """(how old the chain's quotes are in seconds, why they cannot be traded at now or None). NSE stamps the whole
    chain (``records.timestamp``, IST); the quotes carry no time of their own."""
    import pytz

    ts = ch.get("timestamp")
    if not ts:
        return None, MESSAGES["quotes_no_timestamp"]
    try:
        when = pytz.timezone("Asia/Kolkata").localize(datetime.strptime(ts, "%d-%b-%Y %H:%M:%S"))
    except ValueError:
        return None, MESSAGES["quotes_bad_timestamp"].format(ts=ts)
    age = round((now - when).total_seconds())
    if when.date() != now.date():
        return age, MESSAGES["quotes_not_today"].format(day=ts[:11])
    if age < -MAX_CLOCK_AHEAD:
        return age, MESSAGES["quotes_clock_behind"].format(nse_time=ts[-8:], ahead=-age)
    if age > MAX_QUOTE_AGE:
        return age, MESSAGES["quotes_too_old"].format(age=age, limit=MAX_QUOTE_AGE)
    return age, None


def entry_allowed() -> str | None:
    """Why no trade may be entered now, or None. The one session check every entry path asks:
    take() (the only writer of a trade row), take_from_run() before fetching prices, the AI run before recording its pick."""
    return None if _market_open() else MESSAGES["market_closed"]


def exit_allowed() -> str | None:
    """Why a trade cannot be closed now, or None. Only whether the market is open: no entry rule (the entry gate, a
    time window, dedupe) ever stops an exit. A trade past expiry settles at intrinsic value whatever this says."""
    return None if _market_open() else MESSAGES["exit_market_closed"]


class StoreCorrupt(TradeError):
    """trades.json exists but cannot be read: every write is refused (nothing saved over the history) until it is fixed."""


_problem: str | None = None                  # what is wrong with the store, from the last read (None: fine)
_backups: dict[str, tuple[str, str]] = {}    # store path -> (sha256 of the damaged bytes, the copy's name): copied once


def _load() -> list[dict]:
    """Every row on file; [] only when there is no file yet. A file that exists but cannot be read or parsed raises
    StoreCorrupt (after copying it aside once), so no writer can save a short list over the history (audit H1)."""
    global _problem
    if not STORE.exists():
        _problem = None
        return []
    try:
        raw = STORE.read_bytes()
    except OSError as exc:
        _problem = MESSAGES["store_unreadable"].format(why=str(exc)[:160])
        logger.error(_problem)
        raise StoreCorrupt(_problem) from exc
    try:
        rows = json.loads(raw.decode("utf-8"))
        if not isinstance(rows, list) or not all(isinstance(t, dict) for t in rows):
            raise ValueError("not a list of trades")
    except ValueError as exc:                              # a JSON error, bad UTF-8, or the wrong shape
        _problem = MESSAGES["store_damaged"].format(why=str(exc)[:160], copy=_back_up_damaged(raw))
        raise StoreCorrupt(_problem) from exc
    _problem = None
    return rows


def _back_up_damaged(raw: bytes) -> str:
    """Copy the damaged file beside it as trades.json.corrupt-<YYYYmmdd-HHMMSS>, once per damaged content (a copy
    already on disk with the same bytes counts, so a restart does not copy again); the copy's name."""
    sha = hashlib.sha256(raw).hexdigest()
    known = _backups.get(str(STORE))
    if known and known[0] == sha:
        return known[1]
    for old in sorted(STORE.parent.glob(f"{STORE.name}.corrupt-*")):
        try:
            if old.stat().st_size == len(raw) and hashlib.sha256(old.read_bytes()).hexdigest() == sha:
                _backups[str(STORE)] = (sha, old.name)
                return old.name
        except OSError:
            continue
    copy = STORE.with_name(f"{STORE.name}.corrupt-{_clock():%Y%m%d-%H%M%S}")
    try:
        copy.write_bytes(raw)
    except OSError as exc:
        logger.error("trades.json is damaged and the copy %s could not be written (%s)", copy, exc)
        return f"{copy.name} (not written: {exc})"
    _backups[str(STORE)] = (sha, copy.name)
    logger.error("trades.json is damaged: copied to %s; every write to the trade record is refused until it is fixed", copy)
    return copy.name


def store_problem() -> str | None:
    """What is wrong with the trade record file right now (it is read again), or None when it is fine or absent."""
    with _lock:
        with contextlib.suppress(StoreCorrupt):
            _load()
        return _problem


def _save(trades: list[dict]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(trades, indent=1, default=str), encoding="utf-8")
    tmp.replace(STORE)


def _clock() -> datetime:
    """The trade record's one clock: IST, from signals.now_ist() (the same clock the session check reads)."""
    from webapp import signals

    return signals.now_ist()


def _now() -> str:
    return _clock().strftime("%Y-%m-%d %H:%M")


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


def take_from_run(run_id: str, candidate: int, chain_fn=None, source: str = "you", confirm: bool = False) -> dict:
    """Your Take on candidate ``candidate`` of AI run ``run_id``, priced here and now: the run must be today's
    (IST), the market open, the index inside the candidate's entry zone, and every leg quoted on both sides in a
    fresh chain. The entry is that chain's ask for a bought leg and bid for a sold one; the run's price is kept
    beside it. Nothing the page sends is used except the two ids."""
    from webapp import option_chain as oc, signals, strategist as st

    run = st.load_run(run_id or "")
    if not run:
        raise TradeError(MESSAGES["run_not_on_file"])
    if st.run_expired(run):
        raise TradeError(MESSAGES["run_expired"])
    if why := entry_allowed():
        raise TradeError(why)
    trades = run.get("trades") or []
    if not 0 <= candidate < len(trades):
        raise TradeError(MESSAGES["no_such_candidate"].format(n=candidate + 1))
    c = trades[candidate]
    try:
        ch = (chain_fn or oc.chain)(c["symbol"], c["expiry"])
    except Exception as exc:                               # never fall back to the run's prices
        raise TradeError(MESSAGES["prices_unavailable_take"].format(error=str(exc)[:160])) from exc
    age, why = _quote_age(ch, signals.now_ist())
    if why:
        raise TradeError(MESSAGES["nse_refused"].format(why=why), {"spot_at_take": ch.get("spot"), "in_entry_zone": None, "quote_age_s": age})
    plan, spot = c["plan"], ch["spot"]
    lo, hi = plan.get("underlying_entry_low"), plan.get("underlying_entry_high")
    in_zone = None if lo is None or hi is None else lo <= spot <= hi
    if in_zone is False:
        raise TradeError(MESSAGES["outside_entry_zone"].format(symbol=c["symbol"], spot=spot, lo=lo, hi=hi),
                         {"spot_at_take": spot, "in_entry_zone": False, "quote_age_s": age})
    rows = {r["strike"]: r for r in ch["rows"]}
    for leg in plan["legs"]:
        q = (rows.get(float(leg["strike"])) or {}).get(leg["option_type"].lower())
        if not q or not q.get("bid") or not q.get("ask"):
            raise TradeError(MESSAGES["leg_unquoted"].format(strike=leg["strike"], type=leg["option_type"]),
                             {"spot_at_take": spot, "in_entry_zone": in_zone, "quote_age_s": age})
    sp = st.StrategyPlan(**plan)
    priced = st.price(sp, ch)
    days = (datetime.strptime(c["expiry"], "%d-%b-%Y").date() - signals.now_ist().date()).days
    fresh = c | {"spot": spot, "priced": priced, "levels": st.trade_levels(sp, priced, ch, days), "charges_per_lot": st.charges(priced, 1)}
    shown = {(x["strike"], x["type"], x["action"]): x["price"] for x in c["priced"]["legs"]}
    return take(fresh, source=source, provenance=_provenance(run, run_id, candidate) | {"in_entry_zone": in_zone, "quote_age_s": age},
                shown=shown, confirm=confirm)


def _provenance(run: dict, run_id: str, candidate: int) -> dict:
    """Where a trade came from: the run (id, time, Complete or Quick, its research) and its place in the AI's list."""
    c = run["trades"][candidate]
    return {"run_id": run_id, "candidate": candidate, "run_day": run.get("day"), "run_asked_at": run.get("asked_at"), "spot_at_run": c.get("spot"),
            "mode": run.get("mode"), "ai_rank": c.get("rank"), "research_source": (run.get("agents") or {}).get("source"),
            "ai_why": c.get("ai_why")}


def record_ai_pick(run_id: str, chain_fn=None) -> dict:
    """The AI's #1 of a run, into the AI track record through the same fresh-chain path as your Take. A refusal
    (stale quotes, outside the entry zone, no live quote...) is kept as a "not taken" row with its reason, so a
    missed pick shows instead of a trade at an old price."""
    try:
        return take_from_run(run_id, 0, chain_fn, source="ai")
    except TradeError as exc:
        row = record_refused(run_id, 0, exc, "ai")
        if row is None:
            raise
        return row


def record_refused(run_id: str, candidate: int, exc: TradeError, source: str) -> dict | None:
    """Keep a refused Take (yours, or the AI's pick) as a "not taken" row with its reason, outside the stats. None
    when the run or the trade is not on file (nothing to show)."""
    from webapp import strategist as st

    run = st.load_run(run_id or "") or {}
    cands = run.get("trades") or []
    if not 0 <= candidate < len(cands):
        return None
    c, plan = cands[candidate], cands[candidate]["plan"]
    row = {"id": uuid.uuid4().hex[:10], "taken_at": _now(), "status": "not_taken", "reason": str(exc), "source": source,
           "symbol": c["symbol"], "expiry": c["expiry"], "strategy": plan["strategy"], "bias": plan.get("bias"),
           "index_target": plan.get("underlying_target"), "index_stop": plan.get("underlying_stop"),
           "legs": [{"action": x["action"], "type": x["type"], "strike": x["strike"], "shown_price": x["price"]} for x in c["priced"]["legs"]],
           "ai_confidence": plan.get("confidence"), **_provenance(run, run_id, candidate),
           "spot_at_take": exc.details.get("spot_at_take"), "in_entry_zone": exc.details.get("in_entry_zone"),
           "quote_age_s": exc.details.get("quote_age_s"), "attempts": 1,
           "code_version": build_info.CODE_VERSION, "server_started_at": build_info.STARTED_AT}
    with _lock:
        trades = _load()
        same = _same_bet(trades, row)
        if same and same["status"] == "open":            # the bet is already held: a refusal of it adds nothing
            return same
        if same:                                         # the same trade refused again: one row, the latest reason, the count
            same.update({k: row[k] for k in ("reason", "spot_at_take", "in_entry_zone", "quote_age_s")},
                        last_attempt_at=row["taken_at"], attempts=same.get("attempts", 1) + 1)
            row = same
        else:
            trades.append(row)
        _save(trades)
    _event("refused" if row.get("attempts", 1) == 1 else "refused_again", row, f"{row['reason']} (attempt {row.get('attempts', 1)})")
    return row


def take(result: dict, source: str = "you", provenance: dict | None = None, shown: dict | None = None,
         confirm: bool = False) -> dict:
    """Record the strategist's proposal (``recommend``'s result) as an open one-lot paper trade.
    ``source``: "you" (taken on the Plan tab) or "ai" (every suggestion, recorded automatically).
    A trade that would join a bet already running (find_bet): yours raises BetExists unless ``confirm``; the AI's is
    recorded. Either way the row carries added_to_bet and the event log says who added it."""
    plan, priced = result.get("plan") or {}, result.get("priced")
    if result.get("rejected") or not priced or plan.get("strategy") in (None, "no_trade"):
        raise TradeError(MESSAGES["no_trade_in_suggestion"])
    if why := entry_allowed():
        raise TradeError(why)
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
        "code_version": build_info.CODE_VERSION, "server_started_at": build_info.STARTED_AT,
    }
    trade |= provenance or {}
    if trade["strategy"] in RANGE:
        _as_range_trade(trade)
    with _lock:
        trades = _load()
        same = _same_bet(trades, trade)
        if same and same["status"] == "open":            # already held: one row
            return same
        grouped = [dict(t) for t in trades]              # copies: the bet fields are read time only, never saved
        _group_bets(grouped)
        bet = find_bet(grouped, trade)
        if bet and source == "you" and not confirm:
            started = next(t["taken_at"] for t in grouped if t["id"] == bet)
            raise BetExists(MESSAGES["bet_exists"].format(direction=direction_of(trade["strategy"]), symbol=trade["symbol"],
                                                          bet=bet, started=started),
                            {"bet_id": bet, "bet_started": started})
        if bet:
            trade["added_to_bet"] = bet
        if same:                                         # refused before, taken now: both rows stay, the refusal linked
            same["later_taken"] = {"at": trade["taken_at"][-5:], "id": trade["id"]}
        trades.append(trade)
        _save(trades)
    _event("taken", trade, "entry " + "; ".join(f"{x['action']} {float(x['strike']):.0f} {x['type']} {x['entry']}" for x in trade["legs"])
           + (f"; refused earlier as {same['id']}" if same else ""))
    if bet:
        _event(f"{'override' if source == 'you' else 'auto'}: added to bet {bet}", trade)
    return trade


def direction_of(strategy: str) -> str:
    """The one direction function: bullish, bearish or neutral, from the strategist's own map. A strategy outside
    it (no_trade, anything new) is an error, never a default."""
    from webapp.strategist import DIRECTION

    try:
        return DIRECTION[strategy]
    except (KeyError, TypeError):
        raise ValueError(f"strategy {strategy!r} has no direction: add it to strategist.DIRECTION") from None


BET_FIELDS = ("bet_id", "bet_index", "bet_size", "bet_started")   # read-time only, never saved


def _bet_side(t: dict) -> tuple:
    """What a bet is: whose (you / ai), which index, which direction. The expiry is not part of it."""
    return t.get("source", "you"), t["symbol"], direction_of(t["strategy"])


def _in_a_bet(t: dict) -> bool:
    """Taken trades only: a not-taken row and a row entered outside the session are in no bet (never counted)."""
    return t["status"] in ("open", "closed") and not _outside_session(t)


def find_bet(trades: list[dict], row: dict) -> str | None:
    """The bet ``row`` joins, as its bet_id, or None for a new bet; the one check that both the grouping and the
    "add to this bet?" question use. A trade joins a bet when, at its taken_at, a trade of the same source, symbol and
    direction was open (overnight too), or was taken the same day; trades already grouped carry their bet_id, so
    a chain of overlaps is one bet. The earliest such bet wins."""
    at, side = row["taken_at"], _bet_side(row)
    for t in trades:
        if t is row or t.get("id") == row.get("id") or not _in_a_bet(t) or t["taken_at"] > at or _bet_side(t) != side:
            continue
        if t["status"] == "open" or (t.get("closed_at") or "") > at or t["taken_at"][:10] == at[:10]:
            return t.get("bet_id") or t["id"]
    return None


def _group_bets(trades: list[dict]) -> None:
    """Read time: give every trade in a bet its bet_id (its first trade's id), place, size and start."""
    done, members = [], {}
    for t in sorted((x for x in trades if _in_a_bet(x)), key=lambda x: x["taken_at"]):
        t["bet_id"] = find_bet(done, t) or t["id"]
        done.append(t)
        members.setdefault(t["bet_id"], []).append(t)
    for ms in members.values():
        for i, t in enumerate(ms, 1):
            t.update(bet_index=i, bet_size=len(ms), bet_started=ms[0]["taken_at"])


def _bet_key(t: dict) -> tuple:
    return (t.get("run_day") or (t.get("taken_at") or "")[:10], t["symbol"], t["expiry"], t["strategy"],
            tuple(sorted((x["action"], x["type"], float(x["strike"])) for x in t["legs"])))


def _same_bet(trades: list[dict], row: dict) -> dict | None:
    """The row already on the record for this bet, or None; the one check both writers (take, record_refused) use.
    The AI's: the same day, symbol, expiry, structure and strikes, whichever run it came from. Yours: the same run's
    same trade (a double click); taking the same strikes again from another run is your choice. Only open and
    not-taken rows count: a closed trade is history, so the same trade again is a new row."""
    for t in trades:
        if t.get("source", "you") != row.get("source", "you") or t["status"] not in ("open", "not_taken"):
            continue
        if row.get("source") == "ai":
            if _bet_key(t) == _bet_key(row):
                return t
        elif row.get("run_id") and (t.get("run_id"), t.get("candidate")) == (row.get("run_id"), row.get("candidate")):
            return t
    return None


def _expired(trade: dict, today: date | None = None) -> bool:
    exp = datetime.strptime(trade["expiry"], "%d-%b-%Y").date()
    now = _clock()
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

    view = {"spot": None, "legs": [], "pnl": None, "flags": [], "error": None, "as_of": None, "pending": []}
    if _expired(trade):
        view["flags"].append("expired")
        return view
    try:
        ch = (chain_fn or oc.full_chain)(trade["symbol"], trade["expiry"])     # every strike: a held leg can be far from the money
    except Exception as exc:
        view["error"] = MESSAGES["prices_unavailable"].format(error=str(exc)[:160])
        return view
    rows = {r["strike"]: r for r in ch["rows"]}
    exits = []
    for leg in trade["legs"]:
        q = (rows.get(float(leg["strike"])) or {}).get(leg["type"].lower())
        x = _exit_price(leg, q)
        exits.append(x)
        view["legs"].append({"now": x, "ltp": q["ltp"] if q else None})
        if x is None:
            view["pending"].append(f"{float(leg['strike']):.0f} {leg['type']}")
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


def _bet_stats(closed: list[dict], open_: list[dict]) -> dict:
    """Bets, not trades: a bet with any trade open is open (outside won / lost); a closed bet is won when the sum of
    its trades' net is above zero."""
    bets: dict[str, list[dict]] = {}
    for t in closed + open_:
        bets.setdefault(t.get("bet_id") or t["id"], []).append(t)
    still_open = {b for b, ms in bets.items() if any(t["status"] == "open" for t in ms)}
    sums = [sum(t["net_pnl"] for t in ms) for b, ms in bets.items() if b not in still_open]
    won = len([x for x in sums if x > 0])
    return {"bets": len(bets), "bets_open": len(still_open), "bet_wins": won, "bet_losses": len(sums) - won,
            "bet_win_rate": won / len(sums) * 100 if sums else None}


def _stats(closed: list[dict], open_: list[dict]) -> dict:
    """Net is closed trades only; the open trades' P&L is open_pnl, a line of its own."""
    nets = [t["net_pnl"] for t in closed]
    wins = [x for x in nets if x > 0]
    return _bet_stats(closed, open_) | {"closed": len(closed), "open": len(open_), "net": sum(nets), "wins": len(wins),
            "losses": len([x for x in nets if x <= 0]), "win_rate": len(wins) / len(nets) * 100 if nets else None,
            "avg": sum(nets) / len(nets) if nets else None, "best": max(nets, default=None),
            "worst": min(nets, default=None), "open_pnl": sum((t.get("live") or {}).get("pnl") or 0 for t in open_)}


def _live_mark(t: dict, chain_fn, live: bool) -> dict:
    """mark() as the record uses it: with the market closed the last prices are shown, never acted on (expiry aside)."""
    v = mark(t, chain_fn)
    v["market_closed"] = not live
    if not live and "expired" not in v["flags"]:
        v["flags"] = []                                  # last prices of a closed market: shown, never acted on
    return v


def overview(chain_fn=None) -> dict:
    """Open trades with live marks, closed trades, totals — yours and the AI's separately, the AI's also by evidence
    score. Read only (GET /api/trades): nothing is saved or logged. An open trade the rules would close now shows it
    as ``live["would_settle"]`` (the reason); refresh_open() does the settling."""
    live = exit_allowed() is None                        # closed market: last prices shown, nothing settled (expiry aside)
    problem = None
    with _lock:                                          # the lock covers the file read only, never a chain fetch
        try:
            trades = _load()
        except StoreCorrupt as exc:                      # a read must not crash the page: an empty view that says why
            trades, problem = [], str(exc)
    _repair_range_trades(trades)                         # shown repaired; saved only by refresh_open()
    for t in trades:
        if t["status"] == "open":
            v = _live_mark(t, chain_fn, live)
            d = _settle_decision(t, v)
            v["would_settle"] = d[3] if d and d[0] == "settle" else None
            t["live"] = v
    return _view(trades, problem)


def refresh_open(chain_fn=None) -> dict:
    """Apply the rules to every open trade and save: remember new target / stop flags, settle what reached its
    target, stop or expiry, write events.log. The monitor calls it; GET never does. Returns the same view as
    overview(). Raises StoreCorrupt (nothing written) when trades.json cannot be read."""
    live = exit_allowed() is None
    with _lock:                                          # snapshot; the chains are fetched outside the lock
        snapshot = _load()
    _repair_range_trades(snapshot)                       # in memory, so a range trade is marked by its range
    views = {t["id"]: _live_mark(t, chain_fn, live) for t in snapshot if t["status"] == "open"}
    with _lock:                                          # read again and merge by id: rows changed meanwhile win
        trades = _load()
        changed = _repair_range_trades(trades)
        for t in trades:
            if t["status"] != "open" or t["id"] not in views:   # closed, removed or taken meanwhile: next time
                continue
            v = views[t["id"]]
            t["live"] = v
            if not live and "expired" not in v["flags"]:
                continue
            changed |= _apply_mark(t, v)
        if changed:
            _save([{k: x for k, x in t.items() if k not in ("live", "v2", "outside_session", *BET_FIELDS)} for t in trades])
    return _view(trades, None)


def _apply_mark(t: dict, v: dict) -> bool:
    """Write one live view into its open trade: the last index level, new flags, a settle by rule. True if changed."""
    changed = False
    if v.get("spot") is not None and v["spot"] != t.get("last_spot"):
        t["last_spot"] = v["spot"]
        changed = True
    changed |= _remember_flags(t, v)
    changed |= _auto_settle(t, v)
    return changed


def _view(trades: list[dict], problem: str | None) -> dict:
    """The page's view of the rows (read-time fields only, never saved)."""
    for t in trades:                                     # read-time only, never saved
        t["outside_session"] = t["status"] != "not_taken" and _outside_session(t)
    _group_bets(trades)
    counted = lambda rows: [t for t in rows if not t["outside_session"]]  # noqa: E731
    out = {}
    for who in ("you", "ai"):
        mine = [t for t in trades if t.get("source", "you") == who]
        open_ = sorted((t for t in mine if t["status"] == "open"), key=lambda t: t["taken_at"], reverse=True)
        closed = sorted((t for t in mine if t["status"] == "closed"), key=lambda t: t["closed_at"], reverse=True)
        out[who] = {"open": open_, "closed": closed, "stats": _stats(counted(closed), counted(open_)),
                    "not_taken": sorted((t for t in mine if t["status"] == "not_taken"), key=lambda t: t["taken_at"], reverse=True)}
    days = _v2_days()
    for t in out["ai"]["open"] + out["ai"]["closed"] + out["ai"]["not_taken"]:
        t["v2"] = _v2_link(t, days)
    out["ai"]["v2_stats"] = _stats([t for t in counted(out["ai"]["closed"]) if t["v2"]["counted"]], [t for t in counted(out["ai"]["open"]) if t["v2"]["counted"]])
    out["ai"]["by_score"] = {band: _stats([t for t in counted(out["ai"]["closed"]) if t.get("score_label") == band], [])
                             for band in ("Strong", "Moderate", "Weak")}
    # the page's original keys stay = your trades
    return out | {"open": out["you"]["open"], "closed": out["you"]["closed"], "stats": out["you"]["stats"], "store_problem": problem}


# ---------------------------------------------------------------- the v2 link and the CSV

from webapp.ai_test import FIRST_SESSION, VERSION  # noqa: E402  (one definition, beside the spec it comes from)


def _leg_key(legs: list[dict]) -> list:
    return sorted((x["action"], x["type"], float(x["strike"])) for x in legs)


def _legs_txt(legs: list[dict], key: str = "price") -> str:
    return "; ".join(f"{'B' if x['action'] == 'BUY' else 'S'} {float(x['strike']):.0f} {x['type']} {x[key]:.2f}" for x in legs if x.get(key) is not None)


def _v2_days() -> dict[str, dict]:
    """v2's registry by session date: the structure it registered and its own entry."""
    from tradingagents.research import registry
    from webapp import ai_test

    try:
        rows = registry.read(ai_test.REGISTRY)
    except (OSError, ValueError):
        return {}
    entries = {r["registration"]: r for r in rows if r.get("type") == "strategist_entry"}
    out = {}
    for r in rows:
        if r.get("type") == "strategist":
            e = entries.get(r.get("hash")) or {}
            out[r["date"]] = {"structure": r.get("structure"), "legs": _leg_key(r.get("legs") or []), "outcome": r.get("outcome"),
                              "status": e.get("status"), "entry": _legs_txt(e.get("legs") or []) or None}
    return out


def _v2_link(t: dict, days: dict) -> dict:
    """For an AI #1 row: did v2 register that session, the same trade, and at what entry. Counted = v2 registered this
    same trade on a session it counts."""
    day = t.get("run_day") or (t.get("taken_at") or "")[:10]     # the run's IST session; old rows: the day taken
    r = days.get(day)
    out = {"registered_that_day": bool(r), "same_trade": False, "counted": False, "entry": None, "status": None}
    if day < FIRST_SESSION.isoformat():               # shown for comparison, never counted
        return out | {"note": MESSAGES["v2_before_start"].format(version=VERSION, first=FIRST_SESSION), "entry": r and r["entry"],
                      "status": r and r["status"]}
    if not r:
        return out | {"note": MESSAGES["v2_nothing"].format(version=VERSION)}
    same = r["structure"] == t.get("strategy") and r["legs"] == _leg_key(t.get("legs") or [])
    return out | {"same_trade": same, "counted": same and r["outcome"] == "trade", "entry": r["entry"], "status": r["status"],
                  "note": MESSAGES[("v2_counted_this" if same else "v2_counted_other") if r["outcome"] == "trade" else "v2_recorded"]
                  .format(version=VERSION, outcome=r["outcome"])}


CSV_HEADER = ["view", "source", "status", "taken_at", "closed_at", "symbol", "strategy", "expiry", "legs", "run_id", "candidate",
              "ai_rank", "mode", "run_asked_at", "research_source", "spot_at_run", "spot_at_take", "in_entry_zone", "quote_age_s", "attempts",
              "index_target", "index_stop", "close_reason", "refusal_reason", "is_v2_counted", "v2_entry", "gross_pnl",
              "charges", "net_pnl", "ai_reason"]
MODES = {"quick": "Quick", "full": "Complete"}


def _cell(x) -> str:
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return str(int(x)) if x.is_integer() else f"{x:.2f}"
    return "" if x is None else str(x)


def _money(x) -> str:
    return "" if x is None else f"{float(x):.2f}"


def history_csv() -> str:
    """Every trade, both views and every status, with where it came from. A field the trade never recorded is
    "unknown" (trades before provenance); nothing is filled in by guess."""
    import csv
    import io

    days = _v2_days()
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    try:
        rows = _load()
    except StoreCorrupt as exc:                          # a read must not crash: the header and one row that says why
        w.writerow(["store problem", str(exc)] + [""] * (len(CSV_HEADER) - 2))
        return buf.getvalue()
    for t in sorted(rows, key=lambda t: t.get("taken_at") or ""):
        ai = t.get("source") == "ai"
        known = lambda k, t=t: _cell(t[k]) if k in t else "unknown"  # noqa: E731
        legs = "; ".join(f"{'B' if x['action'] == 'BUY' else 'S'} {float(x['strike']):.0f} {x['type']} shown {_cell(x.get('shown_price')) if 'shown_price' in x else 'unknown'}"
                         f" entry {_cell(x.get('entry'))} exit {_cell(x.get('exit'))}" for x in t["legs"])
        link = _v2_link(t, days) if ai else None
        w.writerow(["AI #1" if ai else "My picks", t.get("source") or "unknown", t["status"], t.get("taken_at"), _cell(t.get("closed_at")),
                    t.get("symbol"), t.get("strategy"), t.get("expiry"), legs, known("run_id"), known("candidate"), known("ai_rank"),
                    MODES.get(t["mode"], t["mode"] or "") if "mode" in t else "unknown", known("run_asked_at"), known("research_source"),
                    known("spot_at_run"),
                    (_cell(t["spot_at_take"]) if "spot_at_take" in t else _cell(t.get("spot_at_entry"))) if "run_id" in t else "unknown",
                    known("in_entry_zone"), known("quote_age_s"), _cell(t.get("attempts")), _cell(t.get("index_target")), _cell(t.get("index_stop")),
                    _cell(t.get("reason")) if t["status"] == "closed" else "", _cell(t.get("reason")) if t["status"] == "not_taken" else "",
                    _cell(bool(link and link["counted"])), _cell(link and link["entry"]),
                    _money(t.get("gross_pnl")), _money(t.get("charges")) if t["status"] == "closed" else "", _money(t.get("net_pnl")),
                    known("ai_why")])
    return buf.getvalue()


def _outside_session(t: dict) -> bool:
    """Entered while the market was closed: its taken_at (IST) falls outside the NSE session. Listed, never counted."""
    import pytz

    when = pytz.timezone("Asia/Kolkata").localize(datetime.strptime(t["taken_at"], "%Y-%m-%d %H:%M"))
    return not _market_open(when)


def _settle(t: dict, exits: list[float], spot: float | None, reason: str) -> dict:
    gross = _pnl(t, exits)
    fee = _charges(t, exits)
    t.update(status="closed", closed_at=_now(), spot_at_exit=spot, reason=reason, gross_pnl=gross, charges=fee,
             net_pnl=gross - fee)
    for leg, x in zip(t["legs"], exits, strict=True):
        leg["exit"] = x
    _event("closed", t, f"{reason}; net {t['net_pnl']:.2f}")
    return t


def _settle_decision(t: dict, v: dict) -> tuple | None:
    """What the rules do with an open trade given its live view, without doing it: ("settle", exits, spot, reason),
    ("exit_pending", None, spot, hit) or None. The stop first if both are reached, then the target, else at expiry."""
    if "expired" in v["flags"]:
        spot = t.get("last_spot") or t["spot_at_entry"]
        return "settle", [_intrinsic(leg, spot) for leg in t["legs"]], spot, MESSAGES["reason_expired"]
    hit = "stop" if "stop" in v["flags"] else "target" if "target" in v["flags"] else None
    if hit and v["pnl"] is None and v.get("pending"):         # it should close, but a leg has no quote
        return "exit_pending", None, v["spot"], hit
    if hit and v["pnl"] is not None:
        return ("settle", [x["now"] for x in v["legs"]], v["spot"],
                MESSAGES["reason_range_broken"] if t.get("range") else MESSAGES["reason_reached"].format(kind=hit))
    return None


def _auto_settle(t: dict, v: dict) -> bool:
    """Close by rule (_settle_decision); a trade that should close but has a leg with no quote says so once."""
    d = _settle_decision(t, v)
    if d is None:
        return False
    kind, exits, spot, why = d
    if kind == "exit_pending":
        if any(a["kind"] == "exit_pending" for a in t["alerts"]):
            return False
        t["alerts"].append({"kind": "exit_pending", "at": _now(), "spot": spot, "legs": v["pending"]})
        _event("exit_pending", t, MESSAGES["event_exit_pending"].format(hit=why, legs=", ".join(v["pending"])), logging.WARNING)
        return True
    _settle(t, exits, spot, why)
    return True


def _repair_range_trades(trades: list[dict]) -> bool:
    """Range trades recorded before the range rule: give them their range, and reopen any that the old rule closed
    by an index target or stop (it was never a real exit). Runs once per trade: afterwards each carries a range."""
    changed = False
    for t in trades:
        if t.get("strategy") not in RANGE or t.get("range"):
            continue
        _as_range_trade(t)
        if t["status"] == "closed" and t.get("reason") in ("target reached", "stop reached"):   # the old rows' stored values
            for k in ("closed_at", "spot_at_exit", "reason", "gross_pnl", "net_pnl"):
                t.pop(k, None)
            for leg in t["legs"]:
                leg.pop("exit", None)
            t.update(status="open", alerts=[], note=MESSAGES["range_bug_note"])
        changed = True
    return changed


def close(trade_id: str, chain_fn=None) -> dict:
    """Close an open trade at the live close-out prices (after expiry: at intrinsic value from the last index level)."""
    from webapp import option_chain as oc

    def find(trades: list[dict]) -> dict:
        t = next((x for x in trades if x["id"] == trade_id), None)
        if t is None:
            raise TradeError(MESSAGES["unknown_trade"])
        if t["status"] != "open":
            raise TradeError(MESSAGES["already_closed"])
        return t

    with _lock:                                          # check first; the chain is fetched outside the lock
        snap = find(_load())
        expired = _expired(snap)
    v = None
    if not expired:
        if why := exit_allowed():
            raise TradeError(why)
        v = mark(snap, chain_fn or oc.full_chain)
        if v["error"] or v["pnl"] is None:
            raise TradeError(v["error"] or MESSAGES["leg_no_price"])
    with _lock:                                          # read again: closed or removed meanwhile is refused
        trades = _load()
        t = find(trades)
        if v is None:
            spot = t.get("last_spot") or t["spot_at_entry"]
            exits = [_intrinsic(leg, spot) for leg in t["legs"]]
            reason = MESSAGES["reason_expired"]
        else:
            exits, spot = [x["now"] for x in v["legs"]], v["spot"]
            reason = (" + ".join(MESSAGES["reason_reached"].format(kind=a["kind"]) for a in t["alerts"])
                      or MESSAGES["reason_by_you"])
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
            raise TradeError(MESSAGES["unknown_trade"])
        _save(keep)
    _event("removed", next(t for t in trades if t["id"] == trade_id), MESSAGES["event_removed"])


# ---------------------------------------------------------------- background monitor

_monitor_started = False
_monitor_lock = threading.Lock()                 # guards _monitor_started and _monitor
_monitor = {"running": False, "last_ok_at": None, "last_error": None, "fail_count": 0}


def monitor_status() -> dict:
    """The monitor's health: running, the last good check (IST), the last error, consecutive failures."""
    with _monitor_lock:
        return dict(_monitor)


def _monitor_tick() -> bool:
    """One check: while the market is open and a trade is open, apply the rules (refresh_open). A failure is logged
    with its traceback and counted, never raised, so the monitor keeps going. True when the check succeeded."""
    from webapp import signals

    try:
        with _lock:
            any_open = any(t["status"] == "open" for t in _load())
        if any_open and signals.market_open():
            refresh_open()
    except Exception as exc:                               # a failed check must not stop the monitor: log and count it
        with _monitor_lock:
            _monitor["fail_count"] += 1
            _monitor["last_error"] = f"{_clock():%Y-%m-%d %H:%M:%S} {type(exc).__name__}: {str(exc)[:300]}"
            n = _monitor["fail_count"]
        logger.exception("trade record monitor: the check failed (%d in a row)", n)
        return False
    with _monitor_lock:
        _monitor.update(last_ok_at=_clock().strftime("%Y-%m-%d %H:%M:%S"), last_error=None, fail_count=0)
    return True


def start_monitor(every_seconds: int = 60) -> None:
    """Check open trades once a minute while the market is open, so a target / stop reached while the page is
    closed still closes the trade at that minute's prices. Starts one thread, however many callers."""
    global _monitor_started
    with _monitor_lock:
        if _monitor_started:
            return
        _monitor_started = True

    def loop():
        import time

        with _monitor_lock:
            _monitor["running"] = True
        try:
            while True:
                time.sleep(every_seconds)
                _monitor_tick()
        finally:                                           # only a BaseException gets here
            with _monitor_lock:
                _monitor["running"] = False

    threading.Thread(target=loop, daemon=True, name="trade-record-monitor").start()
