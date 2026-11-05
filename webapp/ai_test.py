"""The AI strategist's forward test, version 2: write each trade to the registry before entry (docs/ai_strategist_test_v2.json, docs/PA_52).

Version 1.1 (one suggestion a question) was closed by the user on 2026-11-04 with one trade registered; its spec and registry stay on file,
unedited, and are not settled or reported. Version 2 counts the AI's #1 of its ranked trades.

One NIFTY question per session counts: the #1 of the first asked in the window. Order: the LLM answers; the structure is registered; only then is a
fresh chain fetched, and the entry is that chain's bid and ask, so no entry price is older than its registration. The rule-based pick is
built from the same fresh chain, and the chain is saved for the random baseline. A changed prompt or model refuses to count: that is a
new test. Nothing here runs by itself: it only acts when the user asks for a suggestion. This is a test of a paper entry, not of real fills.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytz

from tradingagents.research import registry

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "docs" / "ai_strategist_test_v2.json"
SPEC_SHA256 = "30dbdfecc54475ab412c1a00556126807d834944c6469ef6d24f04127f697392"
REGISTRY = ROOT / "reports" / "ai_test" / "v2" / "registry.jsonl"     # version 1.1's stays at reports/ai_test/registry.jsonl
CHAINS = ROOT / "reports" / "ai_test" / "v2" / "chains"
IST = pytz.timezone("Asia/Kolkata")
SYMBOL = "NIFTY"
WINDOW = (time(9, 30), time(15, 0))
# The spec's "starts" is a rule: "the first weekday session after this file is on main". The frozen file reached main
# with PR #98, merged 2026-11-04 13:50 IST, so the first counted session is 2026-11-05. Everything else reads this.
V2_FIRST_SESSION = date(2026, 11, 5)


def read_spec(path: Path | None = None) -> dict:
    spec = json.loads((path or SPEC_FILE).read_text(encoding="utf-8"))
    text = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != SPEC_SHA256:
        raise ValueError("ai_strategist_test_v2.json changed after it was frozen")
    return spec


def prompt_fingerprint() -> str:
    """Hash of what the ranking LLM is told and how its list is built: the system prompt, the answer schema, the strategy menu, and the
    code that runs the research, builds the context and the candidates, and asks. The research agents' own prompts are not covered."""
    from webapp import morning, strategist as st

    def lf(text: str) -> str:
        return text.replace("\r\n", "\n")

    code = (st.ask_rank_llm, st.ai_ranked, st.candidates_for_ai, st.today_moves, st.agents_view, st.today_research, st.build_context, st.rank, st._structures,
            st._index_levels, st.trade_levels, st.price, st.check_structure, morning.ai_view)
    parts = {"system": lf(st.RANK_SYSTEM), "schema": st.RankedAnswer.model_json_schema(), "strategies": {k: v[0] for k, v in st.STRATEGIES.items()},
             "top": st.TOP_AI, "code": {f.__name__: lf(inspect.getsource(f)) for f in code}}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()


def fingerprint_problem(spec: dict | None = None) -> str | None:
    """Why answers would not count because the code or model differs from the frozen spec, or None. Never fixes it:
    the fingerprint in the spec is only ever changed by freezing a new test."""
    spec = spec or read_spec()
    if prompt_fingerprint() != spec["version"]["prompt_sha256"]:
        return "the prompt fingerprint differs from the frozen spec: fingerprinted code changed, so no answer counts until it is undone or a new test is frozen"
    if model_settings() != spec["version"]["model"]:
        return "the model settings differ from the frozen spec, so no answer counts until they are restored or a new test is frozen"
    return None


def today_status(now: datetime | None = None) -> dict:
    """Did today's answer count: YES, NO, NOT YET or NO SESSION, with the reason."""
    from webapp import signals, trade_record

    now = (now or datetime.now(IST)).astimezone(IST)
    day, fp = now.date(), fingerprint_problem()
    out = {"day": day.isoformat(), "fingerprint_problem": fp}
    if day < V2_FIRST_SESSION:
        return out | {"state": "NO", "reason": f"before v2 started ({V2_FIRST_SESSION})"}
    if not signals.nse_calendar().is_trading_day(day):
        return out | {"state": "NO SESSION", "reason": "no NSE session today"}
    rows = registry.read(REGISTRY)
    mine = [r for r in rows if r.get("date") == day.isoformat() and r.get("spec_hash") == SPEC_SHA256]
    reg = next((r for r in mine if r["type"] == "strategist"), None)
    if reg:
        at = reg["timestamp"][11:16]
        if reg["outcome"] != "trade":
            return out | {"state": "YES", "reason": f"the first answer, at {at}, counted as {reg['outcome']} (an answer, not a trade); later runs today do not count"}
        entry = next((r for r in rows if r.get("type") == "strategist_entry" and r.get("registration") == reg["hash"]), None)
        if entry is None:
            return out | {"state": "NO", "reason": f"registered at {at}, but no entry was written"}
        if entry["status"] != "entered":
            return out | {"state": "NO", "reason": f"void entry at {at}: {entry.get('reason', 'no reason recorded')}"}
        return out | {"state": "YES", "reason": f"the first answer, at {at}, counted: {reg['structure']} entered at {trade_record._legs_txt(entry['legs'])}; later runs today do not count"}
    if any(r["type"] == "missed" for r in mine):
        return out | {"state": "NO", "reason": "recorded as missed"}
    if fp:
        return out | {"state": "NO", "reason": f"fingerprint mismatch: {fp}"}
    if now.time() < WINDOW[0]:
        return out | {"state": "NOT YET", "reason": "the window opens at 09:30; the first run between 09:30 and 15:00 counts"}
    if now.time() <= WINDOW[1]:
        return out | {"state": "NOT YET", "reason": "run an analysis before 15:00: the first one counts"}
    return out | {"state": "NO", "reason": "no answer between 09:30 and 15:00: today will be recorded as missed"}


def model_settings() -> dict:
    from tradingagents.default_config import build_default_config

    c = build_default_config()
    return {"provider": c.get("llm_provider"), "model": c.get("deep_think_llm"), "quick_model": c.get("quick_think_llm"),
            "reasoning_effort": os.environ.get("TRADINGAGENTS_OPENAI_REASONING_EFFORT")}


def _weekdays_between(a: date, b: date) -> list[date]:
    """Weekdays after a and before b. A holiday among them is corrected against NSE's sessions when results are settled."""
    return [a + timedelta(days=i) for i in range(1, (b - a).days) if (a + timedelta(days=i)).weekday() < 5]


def record(result: dict, path: Path | None = None, chains: Path | None = None, now: datetime | None = None, built=None, spec: dict | None = None, clock=None) -> dict | None:
    """Register the first NIFTY answer of a session: ``result`` is its #1 trade (a no_trade plan when the AI ranked none).
    Returns the registry row, or None if this answer does not count."""
    from webapp import strategist as st

    path, chains = path or REGISTRY, chains or CHAINS
    spec = spec or read_spec()
    now = now or datetime.now(IST)
    clock = clock or (lambda: datetime.now(IST))
    if result.get("symbol") != SYMBOL or not WINDOW[0] <= now.time() <= WINDOW[1] or now.weekday() >= 5:
        return None
    if "stop" in spec and now.date() > date.fromisoformat(spec["stop"]["date"]):
        return None
    if why := fingerprint_problem(spec):
        logger.warning("this answer does not count: %s", why)
        return None
    rows = registry.read(path)
    day = now.date()
    if any(r.get("date") == day.isoformat() for r in rows if r["type"] in ("strategist", "missed")):
        return None
    spec_hash = SPEC_SHA256
    seen = [date.fromisoformat(r["date"]) for r in rows if r["type"] in ("strategist", "missed")]
    if seen:
        for d in _weekdays_between(max(seen), day):
            registry.record_missed(path, day=d, spec_hash=spec_hash, now=now, reason="no question asked in the window")
    plan = result.get("plan") or {}
    trade = bool(result.get("priced")) and plan.get("strategy") not in (None, "no_trade")
    row = registry.register_structure(
        path, day=day, symbol=SYMBOL, expiry=result.get("expiry"), spec_hash=spec_hash, now=now, outcome="trade" if trade else "rejected" if result.get("rejected") else "no_trade",
        structure=plan.get("strategy"), direction=plan.get("bias"), legs=[{"action": x["action"], "type": x["option_type"], "strike": x["strike"]} for x in plan.get("legs", [])] if trade else [],
        max_risk_indicative=(result.get("priced") or {}).get("max_loss_per_lot"))
    if not trade:
        return row
    ctx, ch = built or st.build_context(SYMBOL, result.get("expiry"))     # fetched only after the row above was written
    try:
        priced = st.price(st.StrategyPlan(**plan), ch)
        if any(not x["bid"] or not x["ask"] for x in priced["legs"]):
            raise ValueError("no two-sided quote")
    except (KeyError, TypeError, ValueError) as exc:
        registry.record_entry(path, registration=row["hash"], now=clock(), status="void", reason=f"{type(exc).__name__}: {str(exc)[:120]}")
        return row
    pick = (st.rank(SYMBOL, result.get("expiry"), top=1, built=(ctx, ch)).get("candidates") or [None])[0]
    chains.mkdir(parents=True, exist_ok=True)
    text = json.dumps(ch, default=str, sort_keys=True)
    chain_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (chains / f"{chain_hash}.json").write_text(text, encoding="utf-8")
    registry.record_entry(path, registration=row["hash"], now=clock(), status="entered", legs=[{k: x[k] for k in ("action", "type", "strike", "price")} for x in priced["legs"]], spot=ch.get("spot"), lot=priced["lot"],
                          max_risk=priced["max_loss_per_lot"], net_per_unit=priced["net_per_unit"], charges=st.charges(priced, 1), chain_sha256=chain_hash,
                          rule_pick={"strategy": pick["plan"]["strategy"], "legs": [{k: x[k] for k in ("action", "type", "strike", "price")} for x in pick["priced"]["legs"]], "max_risk": pick["priced"]["max_loss_per_lot"], "charges": pick["charges_per_lot"]} if pick else None)
    return row
