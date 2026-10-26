"""Plan tab: the complete AI analysis runs once per instrument, is saved, and feeds the AI strategist's trade."""

import threading
import time
from datetime import date

import pytest

from tests.test_strategist import CHAIN
from webapp import analysis as an, market_data as md, strategist as st

STATE = {"final_rating": "Underweight", "final_trade_decision": "Lean bearish below 22,700.",
         "market_report": "Below the 21-day average.", "news_report": "Quiet session."}


@pytest.fixture
def runs(monkeypatch, tmp_path):
    monkeypatch.setattr(an, "DIR", tmp_path)
    monkeypatch.setattr(an, "_running", {})
    monkeypatch.setattr(md, "instrument", lambda s: {"symbol": s.upper(), "name": "NIFTY 50", "yahoo": "^NSEI"})
    return tmp_path


def _wait(sym, status="running", timeout=5.0):
    end = time.time() + timeout
    while an.status(sym)["status"] == status and time.time() < end:
        time.sleep(0.02)
    return an.status(sym)


def _runner(ticker, analysts, on_step):
    assert ticker == "^NSEI" and set(analysts) == {"market", "news", "social", "fundamentals"}
    on_step("Price & indicator analysis done")
    on_step("Risk team signed off")
    return STATE


@pytest.mark.unit
def test_the_analysis_runs_then_the_strategy_is_built_from_it_and_saved(runs):
    seen = {}

    def strategist(symbol, expiry, analysis):
        seen.update(symbol=symbol, expiry=expiry, analysis=analysis)
        return {"strategy_text": "Bear call spread", "asked_at": "2026-10-26 11:02", "priced": None}

    an.start("nifty", "27-Oct-2026", runner=_runner, strategist_fn=strategist)
    done = _wait("NIFTY")
    assert done["status"] == "done" and done["rating"] == "Underweight"
    assert done["reports"]["Final decision"].startswith("Lean bearish") and "News" in done["reports"]
    assert done["steps"][-1] == an.STRATEGY_STEP and done["strategy"]["strategy_text"] == "Bear call spread"
    assert seen["symbol"] == "NIFTY" and seen["expiry"] == "27-Oct-2026"
    assert seen["analysis"]["reports"]["Final decision"].startswith("Lean bearish")    # the strategist got the analysis
    assert an.load("NIFTY")["status"] == "done" and "phase" not in done                # survives a restart


@pytest.mark.unit
def test_one_run_per_instrument_at_a_time(runs):
    release, calls = threading.Event(), []

    def slow(ticker, analysts, on_step):
        calls.append(1)
        release.wait(5)
        return STATE

    first = an.start("NIFTY", runner=slow, strategist_fn=lambda *a, **k: {"asked_at": "x"})
    second = an.start("NIFTY", runner=slow, strategist_fn=lambda *a, **k: {"asked_at": "x"})
    assert first["status"] == second["status"] == "running" and first["started"] == second["started"]
    assert an.status("NIFTY")["phase"] == "analysis"
    release.set()
    assert _wait("NIFTY")["status"] == "done" and len(calls) == 1


@pytest.mark.unit
def test_a_failed_analysis_is_saved_as_an_error_and_can_run_again(runs):
    def broken(ticker, analysts, on_step):
        raise RuntimeError("Azure rejected the key (401)")

    an.start("NIFTY", runner=broken)
    failed = _wait("NIFTY")
    assert failed["status"] == "error" and "401" in failed["error"] and "NIFTY" not in an._running
    an.start("NIFTY", runner=_runner, strategist_fn=lambda *a, **k: {"asked_at": "x"})
    assert _wait("NIFTY")["status"] == "done"


@pytest.mark.unit
def test_a_failed_strategy_keeps_the_analysis(runs):
    def strategist(*a, **k):
        raise ValueError("NSE chain unavailable")

    an.start("NIFTY", runner=_runner, strategist_fn=strategist)
    done = _wait("NIFTY")
    assert done["status"] == "done" and done["reports"] and "NSE chain unavailable" in done["strategy_error"]
    assert an.STRATEGY_STEP not in done["steps"]


@pytest.mark.unit
def test_nothing_run_yet():
    assert an.status("NOSUCH")["status"] == "none"


@pytest.mark.unit
def test_the_strategist_context_carries_the_analysis_instead_of_the_morning_view(monkeypatch):
    from webapp import morning, option_chain as oc, planner

    monkeypatch.setattr(oc, "chain", lambda s, e=None: CHAIN)
    monkeypatch.setattr(planner, "plan", lambda s: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(morning, "context", lambda s, d: {})
    monkeypatch.setattr(morning, "load", lambda: {"indices": {"NIFTY": {"ai": {"rating": "Buy", "decision": "old"}}}})
    run = {"rating": "Underweight", "finished": "2026-10-26 11:01",
           "reports": {"Final decision": "Lean bearish.", "News": "x" * 5000}}
    ctx, _ = st.build_context("NIFTY", None, run)
    assert ctx["ai_analysis"]["rating"] == "Underweight" and ctx["ai_analysis"]["final_decision"] == "Lean bearish."
    assert len(ctx["ai_analysis"]["news"]) == 1200 and "morning_ai_view" not in ctx
    ctx, _ = st.build_context("NIFTY", None)
    assert ctx["morning_ai_view"]["rating"] == "Buy" and "ai_analysis" not in ctx


@pytest.mark.unit
def test_ask_again_uses_only_todays_finished_analysis(monkeypatch):
    today = date.today().isoformat()
    for saved, expect in [({"status": "done", "finished": f"{today} 11:01"}, True),
                          ({"status": "done", "finished": "2020-01-01 11:01"}, False),
                          ({"status": "error", "finished": f"{today} 11:01"}, False), (None, False)]:
        monkeypatch.setattr(an, "load", lambda s, saved=saved: saved)
        assert (st.todays_analysis("NIFTY") is not None) is expect
