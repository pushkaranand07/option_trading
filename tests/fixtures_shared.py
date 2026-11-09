"""Fixtures shared by several test modules, registered in conftest.py through ``pytest_plugins``.

A test module asks for one by naming it as an argument; it does not import it (importing a fixture by name and then
using it as an argument is a redefinition, ruff F811). A module that defines a fixture of the same name keeps its own.
The helpers and data the fixtures use stay in the test modules they came from."""

import time

import pytest

from tests.test_bug1_far_legs import CONDOR, NEAR, chain as condor_chain
from tests.test_take_honest_entry import EXPIRY, at, chain
from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from webapp import ai_test, option_chain as oc, signals, strategist as st, trade_record as tr


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(st, "_runs_dir", lambda: tmp_path / "runs")
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    clock = {"now": at(10, 0)}
    monkeypatch.setattr(signals, "now_ist", lambda: clock["now"])
    live = {"chain": chain()}

    def fetch(symbol, expiry):
        if isinstance(live["chain"], Exception):
            raise live["chain"]
        ch = live["chain"]                               # NSE stamps each chain; a test that sets none gets "now"
        return ch if "timestamp" in ch else ch | {"timestamp": clock["now"].strftime("%d-%b-%Y %H:%M:%S")}

    monkeypatch.setattr(oc, "chain", fetch)
    ctx = {"spot": 22600, "days_to_expiry": 22, "expected_move": {"day_pct": 0.01}, "option_chain": {"summary": chain()["summary"]}}
    cands = st.rank("NIFTY", built=(ctx, chain()), top=50)["candidates"]
    call = next(c for c in cands if c["plan"]["strategy"] == "long_call" and c["priced"]["legs"][0]["strike"] == 22600.0)
    spread = next(c for c in cands if c["plan"]["strategy"] == "bull_call_spread")
    run = {"symbol": "NIFTY", "expiry": EXPIRY, "spot": 22600, "lot": 65, "trades": [call, spread], "asked_at": "2026-11-12 09:58",
           "run_id": "run1", "day": "2026-11-12"}
    st.save_run(run)
    return {"clock": clock, "live": live, "run": run, "call": call}


@pytest.fixture
def condor(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "STORE", tmp_path / "trades.json")
    monkeypatch.setattr(tr, "_market_open", lambda *a: True)
    t = tr.take(CONDOR, source="ai")
    monkeypatch.setattr(oc, "chain", lambda *a, **k: condor_chain(NEAR))           # the display window: the puts fell out
    return t


@pytest.fixture
def run_ai(world, monkeypatch):
    """Run start() to the end with the ranking replaced by the fixture's run (its prices are the run's)."""
    monkeypatch.setattr(st, "agents_view", lambda symbol: {"rating": "Hold", "decision": "d"})
    monkeypatch.setattr(st, "save_research", lambda symbol, r, day=None: r)
    monkeypatch.setattr(ai_test, "record", lambda *a, **k: None)
    ranked = {k: v for k, v in world["run"].items() if k not in ("run_id", "day")}
    monkeypatch.setattr(st, "ai_ranked", lambda *a, **k: dict(ranked, trades=list(ranked["trades"])))

    def go():
        job = st.start("NIFTY", mode="full")
        for _ in range(200):
            j = st.job(job)
            if j["status"] != "running":
                return j
            time.sleep(0.02)
        raise AssertionError("the run did not finish")
    return go
