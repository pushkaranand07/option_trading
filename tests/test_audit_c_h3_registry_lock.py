"""Audit H3: the forward-test registry is written from per-request background threads (strategist.start), so two
analyses can race. Every check-then-append in ``registry`` and the read -> decide -> register sequence in
``ai_test.record`` must hold one lock: no duplicate session day, an intact hash chain, and no two rows that claim the
same previous row."""

import threading
from collections import Counter
from datetime import date, datetime, timedelta

import pytest
import pytz

from tradingagents.dataflows.vendors.nse.calendar import NSECalendar
from tradingagents.research import registry
from webapp import ai_test, signals

IST = pytz.timezone("Asia/Kolkata")
THREADS, ROUNDS = 20, 30
BASE = date(2027, 1, 4)                                              # a Monday


def at(day, hour=10, minute=0):
    return IST.localize(datetime(day.year, day.month, day.day, hour, minute))


def weekdays(n):
    out, d = [], BASE
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _check(path):
    rows = registry.read(path)
    registry.verify(path)                                            # raises on a broken chain
    prevs = [r["prev_hash"] for r in rows]
    assert len(prevs) == len(set(prevs)), "two rows claim the same previous row"
    days = Counter((r["date"], r["spec_hash"]) for r in rows if r["type"] in ("strategist", "missed"))
    assert all(v == 1 for v in days.values()), f"duplicate session days: {[k for k, v in days.items() if v > 1]}"
    entries = Counter(r["registration"] for r in rows if r["type"] == "strategist_entry")
    assert all(v == 1 for v in entries.values()), "a registration has two entries"
    return rows


def _race(target, args_list):
    barrier = threading.Barrier(len(args_list))
    errors = []

    def go(args):
        barrier.wait()
        try:
            target(*args)
        except registry.RegistryError:
            pass                                                     # a refused duplicate is the correct answer
        except Exception as exc:                                     # anything else is a failure of the test
            errors.append(exc)

    threads = [threading.Thread(target=go, args=(a,)) for a in args_list]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors


def _structure(path, day):
    registry.register_structure(path, day=day, symbol="NIFTY", expiry="28-Jan-2027", spec_hash="s", now=at(day), outcome="no_trade",
                                structure=None, direction=None, legs=[], max_risk_indicative=None)


@pytest.mark.unit
def test_register_structure_from_many_threads_on_the_same_day_writes_one_row(tmp_path):
    for i in range(ROUNDS):
        path = tmp_path / f"same{i}.jsonl"
        _race(_structure, [(path, BASE)] * THREADS)
        rows = _check(path)
        assert len(rows) == 1


@pytest.mark.unit
def test_register_structure_from_many_threads_on_different_days_keeps_the_chain(tmp_path):
    days = weekdays(THREADS)
    for i in range(ROUNDS):
        path = tmp_path / f"diff{i}.jsonl"
        _race(_structure, [(path, d) for d in days])
        rows = _check(path)
        assert sorted(r["date"] for r in rows) == sorted(d.isoformat() for d in days)


@pytest.fixture
def fakes(monkeypatch):
    """The strategist and the chain are fakes: no network, no LLM."""
    from webapp import strategist as st

    monkeypatch.setattr(ai_test, "prompt_fingerprint", lambda: "fp")
    monkeypatch.setattr(ai_test, "model_settings", lambda: {"m": 1})
    monkeypatch.setattr(signals, "nse_calendar", lambda: NSECalendar(holidays={}))
    priced = {"legs": [{"action": "BUY", "type": "CE", "strike": 100.0, "price": 5.0, "bid": 4.9, "ask": 5.0}], "lot": 65,
              "max_loss_per_lot": 325.0, "net_per_unit": 5.0}
    monkeypatch.setattr(st, "StrategyPlan", lambda **k: k)
    monkeypatch.setattr(st, "price", lambda plan, ch: priced)
    monkeypatch.setattr(st, "charges", lambda p, lots: 55.0)
    monkeypatch.setattr(st, "rank", lambda *a, **k: {"candidates": []})
    monkeypatch.setattr(st, "build_context", lambda *a: ({}, {"spot": 101.0, "rows": []}))
    return {"version": {"prompt_sha256": "fp", "model": {"m": 1}}}


RESULT = {"symbol": "NIFTY", "expiry": "28-Jan-2027", "priced": {"max_loss_per_lot": 500.0},
          "plan": {"strategy": "long_call", "bias": "bullish", "legs": [{"action": "BUY", "option_type": "CE", "strike": 100.0}]}}


def _record(path, chains, spec, now):
    ai_test.record(RESULT, path, chains, now, spec=spec, clock=lambda: now + timedelta(minutes=1))


@pytest.mark.unit
def test_record_from_many_threads_on_the_same_day_registers_once(tmp_path, fakes):
    for i in range(ROUNDS):
        path, chains = tmp_path / f"rec{i}.jsonl", tmp_path / f"c{i}"
        _race(_record, [(path, chains, fakes, at(BASE))] * THREADS)
        rows = _check(path)
        assert [r["type"] for r in rows] == ["strategist", "strategist_entry"]


@pytest.mark.unit
def test_record_from_many_threads_on_different_days_never_duplicates_a_day(tmp_path, fakes):
    days = weekdays(THREADS)
    for i in range(ROUNDS):
        path, chains = tmp_path / f"recd{i}.jsonl", tmp_path / f"cd{i}"
        _race(_record, [(path, chains, fakes, at(d)) for d in days])
        rows = _check(path)
        got = [r["date"] for r in rows if r["type"] in ("strategist", "missed")]
        assert sorted(got) == sorted(d.isoformat() for d in days)    # each day once: registered, or missed by a later one


@pytest.mark.unit
def test_the_lock_is_reentrant_and_released(tmp_path):
    path = tmp_path / "r.jsonl"
    with registry.locked(path), registry.locked(path):              # nested in one thread: no deadlock
        _structure(path, BASE)
    done = []

    def other():
        with registry.locked(path):
            done.append(1)

    t = threading.Thread(target=other)
    t.start()
    t.join(10)
    assert done == [1]                                               # free again for another thread


@pytest.mark.unit
def test_another_process_holding_the_lock_makes_a_writer_wait(tmp_path):
    import subprocess
    import sys

    path = tmp_path / "r.jsonl"
    code = ("import sys, time; from tradingagents.research import registry\n"
            "with registry.locked(sys.argv[1]):\n    print('held', flush=True); time.sleep(4)\n")
    proc = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True,
                            cwd=str(registry.Path(registry.__file__).resolve().parents[2]))
    try:
        assert proc.stdout.readline().strip() == "held"
        with pytest.raises(registry.RegistryError, match="locked by another process"), registry.locked(path, timeout=0.3):
            pass
    finally:
        proc.wait(20)
    with registry.locked(path, timeout=5):                         # released when the other process let go
        _structure(path, BASE)
    assert registry.verify(path) == 1
