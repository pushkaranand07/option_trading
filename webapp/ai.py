"""TradingAgents deep analysis on Azure OpenAI, run as background jobs the page polls."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import date, datetime

STEP_LABELS = {
    "market_report": "Price & indicator analysis done",
    "news_report": "News analysis done",
    "sentiment_report": "Social sentiment analysis done",
    "fundamentals_report": "Fundamentals analysis done",
    "investment_plan": "Bull vs bear debate settled",
    "trader_investment_plan": "Trader drafted a plan",
    "final_trade_decision": "Risk team signed off",
}
REPORTS = {
    "Final decision": "final_trade_decision",
    "Price & indicators": "market_report",
    "News": "news_report",
    "Social sentiment": "sentiment_report",
    "Fundamentals": "fundamentals_report",
    "Trader's plan": "trader_investment_plan",
}

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def azure_problem() -> str | None:
    missing = [k for k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT_NAME")
               if not os.environ.get(k)]
    return f"Add {', '.join(missing)} to .env and restart." if missing else None


def start(symbol: str, yahoo_symbol: str, analysts: list[str]) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"id": job_id, "symbol": symbol, "status": "running", "steps": [],
                         "started": datetime.now().strftime("%H:%M")}
    threading.Thread(target=_run, args=(job_id, yahoo_symbol, analysts), daemon=True).start()
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


ANALYSTS = ["market", "news", "social", "fundamentals"]


def run_analysis(ticker: str, analysts: list[str], on_step=None) -> dict:
    """The full multi-agent analysis of ``ticker`` today; ``on_step(label)`` is called as each stage finishes.
    Returns the final graph state; raises with a plain message when Azure rejects the key."""
    from tradingagents.dataflows.config import run_config
    from tradingagents.default_config import build_default_config
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    try:
        graph = TradingAgentsGraph(selected_analysts=analysts, config=build_default_config())
        trade_date = date.today().isoformat()
        done: list[str] = []
        # The same steps as TradingAgentsGraph.propagate, streamed to report progress.
        with run_config(graph.config):
            init = graph.create_run_state(ticker, trade_date)
            final_state: dict = {}
            for _messages, state in graph.stream_run(init, **graph.propagator.get_graph_args()):
                if state is None:
                    continue
                final_state.update(state)
                for key, label in STEP_LABELS.items():
                    if final_state.get(key) and label not in done:
                        done.append(label)
                        if on_step:
                            on_step(label)
            graph.record_decision(ticker, trade_date, final_state)
        return final_state
    except Exception as exc:
        msg = str(exc)
        if "401" in msg or "PermissionDenied" in type(exc).__name__ or "AuthenticationError" in type(exc).__name__:
            raise RuntimeError("Azure rejected the key (401). Key login may be disabled on this Azure resource; "
                               "enable it under Keys and Endpoint, or use another resource. Details: " + msg[:300]) from exc
        raise


def reports(final_state: dict) -> dict[str, str]:
    return {k: final_state.get(v, "") for k, v in REPORTS.items() if final_state.get(v)}


def _run(job_id: str, ticker: str, analysts: list[str]) -> None:
    job = _jobs[job_id]
    try:
        from tradingagents.agents.rating import run_rating

        final_state = run_analysis(ticker, analysts, job["steps"].append)
        job.update(status="done", rating=run_rating(final_state), finished=datetime.now().strftime("%H:%M"),
                   reports=reports(final_state))
    except Exception as exc:
        job.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:600]}")
