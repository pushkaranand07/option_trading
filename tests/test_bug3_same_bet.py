"""Bug 3: the same bet was recorded several times, because "is this the same trade?" was written three times with three
keys (open AI rows by strikes; refusals by run and candidate; double clicks by run and candidate). One _same_bet()
now serves both writers: for the AI, the same day, symbol, expiry, structure and strikes; for you, the same run's same
trade. It looks at open and not-taken rows only (a closed trade is history, so the same trade again is a new row). A
refusal followed by a Take of the same bet keeps both rows, the refusal linked: "later taken at HH:MM"."""

import inspect
import json
import subprocess
from pathlib import Path

import pytest

from tests.test_take_honest_entry import chain
from webapp import strategist as st, trade_record as tr

ROOT = Path(__file__).resolve().parents[1]
STALE = {"timestamp": "05-Nov-2026 09:55:00"}                                     # 5 minutes old at 10:00: refused


def second_run(world, run_id="run2"):
    st.save_run(world["run"] | {"run_id": run_id})                                 # a re-run with the same #1


def ai(status=None):
    return [t for t in tr._load() if t.get("source") == "ai" and (status is None or t["status"] == status)]


@pytest.mark.unit
def test_the_same_refused_bet_from_two_runs_is_one_row_with_two_attempts(world):
    world["live"]["chain"] = chain() | STALE
    second_run(world)
    tr.record_ai_pick("run1")
    tr.record_ai_pick("run2")
    [row] = ai("not_taken")
    assert row["attempts"] == 2


@pytest.mark.unit
def test_a_refusal_of_a_bet_already_held_adds_no_row(world):
    tr.record_ai_pick("run1")                                                       # taken
    world["live"]["chain"] = chain() | STALE
    second_run(world)
    tr.record_ai_pick("run2")                                                       # the same bet, refused
    assert [t["status"] for t in ai()] == ["open"]


@pytest.mark.unit
def test_a_bet_refused_then_taken_keeps_both_rows_linked(world):
    world["live"]["chain"] = chain() | STALE
    tr.record_ai_pick("run1")
    world["live"]["chain"] = chain()
    second_run(world)
    taken = tr.record_ai_pick("run2")
    [refused] = ai("not_taken")
    assert taken["status"] == "open" and refused["later_taken"]["id"] == taken["id"] and refused["later_taken"]["at"]
    html = subprocess.run(["node", str(ROOT / "tests" / "js" / "render.js"), "notTakenRowsHtml(ARGS[0])"], input=json.dumps([[refused]]),
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert html.returncode == 0 and "later taken at" in html.stdout and taken["id"] in html.stdout


@pytest.mark.unit
def test_the_same_trade_after_the_first_closed_is_a_new_row(world):
    tr.record_ai_pick("run1")
    rows = tr._load()
    rows[0].update(status="closed", closed_at="2026-11-05 10:30", reason="target reached", net_pnl=100.0)
    tr._save(rows)
    second_run(world)
    tr.record_ai_pick("run2")
    assert sorted(t["status"] for t in ai()) == ["closed", "open"]


@pytest.mark.unit
def test_one_same_bet_check_serves_both_writers():
    assert "_same_bet(" in inspect.getsource(tr.take) and "_same_bet(" in inspect.getsource(tr.record_refused)
    assert not hasattr(tr, "_same")                                                 # the old open-only copy is gone
