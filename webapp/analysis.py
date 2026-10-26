"""Plan tab: the complete AI analysis of one instrument, then the AI strategist's trade built from it.

1. The multi-agent analysis (``ai.run_analysis``): price & indicators, news, social sentiment, fundamentals, a
   bull-vs-bear debate, a trader and a risk team. About 15-20 minutes on Azure.
2. ``strategist.recommend`` with that analysis in its context, on the option chain and prices as they are when the
   analysis finishes (about a minute). A valid trade goes into the AI track record, like every AI suggestion.

One run per instrument at a time. The latest run per instrument is saved in ``reports/analysis/`` so it survives a
page reload or a server restart; the page shows when it finished and the price then.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

from webapp import ai, market_data as md

DIR = Path(__file__).resolve().parent.parent / "reports" / "analysis"
STRATEGY_STEP = "Strategy built from the analysis"
STEPS = [*ai.STEP_LABELS.values(), STRATEGY_STEP]

_running: dict[str, dict] = {}
_lock = threading.Lock()


def path_for(symbol: str) -> Path:
    return DIR / f"{symbol.upper()}.json"


def load(symbol: str) -> dict | None:
    f = path_for(symbol)
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        return None


def save(run: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    tmp = path_for(run["symbol"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path_for(run["symbol"]))


def status(symbol: str) -> dict:
    """The running analysis, else the latest saved one, else ``{"status": "none"}``."""
    sym = symbol.upper()
    with _lock:
        run = _running.get(sym)
        if run:
            return {**run, "steps": list(run["steps"])}
    return load(sym) or {"status": "none", "symbol": sym}


def start(symbol: str, expiry: str | None = None, runner=None, strategist_fn=None) -> dict:
    """Start a complete analysis of ``symbol`` (an already running one is returned instead)."""
    inst = md.instrument(symbol)
    sym = inst["symbol"]
    with _lock:
        if sym in _running:
            return {**_running[sym], "steps": list(_running[sym]["steps"])}
        run = {"status": "running", "symbol": sym, "name": inst["name"], "phase": "analysis", "steps": [],
               "started": datetime.now().strftime("%Y-%m-%d %H:%M"), "expiry": expiry}
        _running[sym] = run
    threading.Thread(target=_run, args=(run, inst["yahoo"], runner, strategist_fn), daemon=True).start()
    return {**run, "steps": []}


def _run(run: dict, ticker: str, runner=None, strategist_fn=None) -> None:
    from tradingagents.agents.rating import run_rating
    from webapp import strategist

    started, outcome = datetime.now(), "error"
    try:
        final_state = (runner or ai.run_analysis)(ticker, ai.ANALYSTS, run["steps"].append)
        run.update(rating=run_rating(final_state), reports=ai.reports(final_state),
                   finished=datetime.now().strftime("%Y-%m-%d %H:%M"), phase="strategy",
                   minutes=round((datetime.now() - started).total_seconds() / 60, 1))
        try:
            res = (strategist_fn or strategist.recommend)(run["symbol"], run.get("expiry"), analysis=run)
            if res.get("priced"):                      # every valid AI suggestion goes into the AI track record
                try:
                    from webapp import trade_record
                    res["ai_record"] = trade_record.take(res, source="ai")["id"]
                except Exception:
                    pass
            run["strategy"] = res
            run["steps"].append(STRATEGY_STEP)
        except Exception as exc:                       # the analysis stands; only the strategy failed
            run["strategy_error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        outcome = "done"
    except Exception as exc:
        run.update(error=f"{type(exc).__name__}: {str(exc)[:600]}", finished=datetime.now().strftime("%Y-%m-%d %H:%M"))
    finally:                                           # saved first, so a finished run is never shown before it is kept
        run.pop("phase", None)
        try:
            save({**run, "status": outcome})
        finally:
            with _lock:
                run["status"] = outcome
                _running.pop(run["symbol"], None)
