"""The AI strategist's forward test and the plain labels (docs/ai_strategist_test_v1.json, docs/PA_49)."""

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import pytz

from tradingagents.research import registry
from webapp import ai_test

IST = pytz.timezone("Asia/Kolkata")
APP = (Path(ai_test.__file__).parent / "static" / "app.js").read_text(encoding="utf-8")
MON = date(2027, 1, 4)


def at(day=MON, hour=10, minute=0):
    return IST.localize(datetime(day.year, day.month, day.day, hour, minute))


LEGS = [{"action": "BUY", "option_type": "CE", "strike": 100.0}]
RESULT = {"symbol": "NIFTY", "expiry": "28-Jan-2027", "plan": {"strategy": "long_call", "bias": "bullish", "legs": LEGS}, "priced": {"max_loss_per_lot": 500.0}}


@pytest.fixture
def world(tmp_path, monkeypatch):
    from webapp import strategist as st

    spec = {"version": {"prompt_sha256": "fp", "model": {"m": 1}}}
    monkeypatch.setattr(ai_test, "prompt_fingerprint", lambda: "fp")
    monkeypatch.setattr(ai_test, "model_settings", lambda: {"m": 1})
    order = []
    priced = {"legs": [{"action": "BUY", "type": "CE", "strike": 100.0, "price": 5.0, "bid": 4.9, "ask": 5.0}], "lot": 65, "max_loss_per_lot": 325.0, "net_per_unit": 5.0}
    monkeypatch.setattr(st, "StrategyPlan", lambda **k: k)
    monkeypatch.setattr(st, "price", lambda plan, ch: order.append("priced") or priced)
    monkeypatch.setattr(st, "charges", lambda p, lots: 55.0)
    monkeypatch.setattr(st, "rank", lambda *a, **k: {"candidates": [{"plan": {"strategy": "long_put"}, "priced": {"legs": priced["legs"], "max_loss_per_lot": 300.0}, "charges_per_lot": 50.0}]})

    def build(*a):
        order.append("fresh chain")
        return {}, {"spot": 101.0, "rows": []}

    monkeypatch.setattr(st, "build_context", build)
    return {"path": tmp_path / "r.jsonl", "chains": tmp_path / "c", "spec": spec, "order": order}


def _record(w, result=RESULT, now=None):
    now = now or at()
    return ai_test.record(result, w["path"], w["chains"], now, spec=w["spec"], clock=lambda: now + timedelta(minutes=1))


@pytest.mark.unit
def test_the_trade_is_registered_before_the_fresh_chain_prices_its_entry(world):
    row = _record(world)
    rows = registry.read(world["path"])
    assert [r["type"] for r in rows] == ["strategist", "strategist_entry"] and rows[0]["hash"] == row["hash"]
    for k in ("structure", "legs", "expiry", "max_risk_indicative", "direction", "timestamp", "spec_hash"):
        assert rows[0][k], k
    assert rows[1]["registration"] == row["hash"] and rows[1]["max_risk"] == 325.0 and rows[1]["chain_sha256"]
    assert rows[1]["rule_pick"]["strategy"] == "long_put"
    assert (world["chains"] / f"{rows[1]['chain_sha256']}.json").exists()
    assert world["order"] == ["fresh chain", "priced"] and registry.verify(world["path"]) == 2


@pytest.mark.unit
def test_an_entry_with_no_registration_or_older_than_it_is_refused(world):
    with pytest.raises(registry.RegistryError, match="not registered before entry"):
        registry.record_entry(world["path"], registration="nope", now=at(), status="entered")
    row = registry.register_structure(world["path"], day=MON, symbol="NIFTY", expiry="x", spec_hash="s", now=at(), outcome="trade", structure="long_call", direction="bullish", legs=[{"a": 1}], max_risk_indicative=5.0)
    with pytest.raises(registry.RegistryError, match="older"):
        registry.record_entry(world["path"], registration=row["hash"], now=at() - timedelta(minutes=1), status="entered")
    registry.record_entry(world["path"], registration=row["hash"], now=at(), status="entered")
    with pytest.raises(registry.RegistryError, match="already"):
        registry.record_entry(world["path"], registration=row["hash"], now=at(), status="entered")


@pytest.mark.unit
def test_only_the_first_nifty_answer_in_the_window_counts(world):
    assert _record(world) is not None
    assert _record(world, now=at(minute=30)) is None                               # a second question that day
    assert _record(world, {**RESULT, "symbol": "BANKNIFTY"}, at(MON + timedelta(days=1))) is None
    assert _record(world, now=at(MON + timedelta(days=1), hour=9, minute=0)) is None    # before the window
    assert _record(world, now=at(MON + timedelta(days=1), hour=15, minute=30)) is None  # after it
    assert _record(world, now=at(date(2027, 1, 9))) is None                             # a Saturday


@pytest.mark.unit
def test_a_changed_prompt_or_model_does_not_count(world, monkeypatch):
    monkeypatch.setattr(ai_test, "prompt_fingerprint", lambda: "changed")
    assert _record(world) is None and not world["path"].exists()
    monkeypatch.setattr(ai_test, "prompt_fingerprint", lambda: "fp")
    monkeypatch.setattr(ai_test, "model_settings", lambda: {"m": 2})
    assert _record(world) is None and not world["path"].exists()


@pytest.mark.unit
def test_days_with_no_question_are_recorded_missed_and_cannot_be_filled_later(world):
    _record(world)
    _record(world, now=at(MON + timedelta(days=3)))
    rows = registry.read(world["path"])
    assert [r["date"] for r in rows if r["type"] == "missed"] == ["2027-01-05", "2027-01-06"]
    with pytest.raises(registry.RegistryError, match="already"):
        registry.register_structure(world["path"], day=date(2027, 1, 5), symbol="NIFTY", expiry="x", spec_hash=rows[0]["spec_hash"], now=at(date(2027, 1, 5)), outcome="no_trade", structure=None, direction=None, legs=[], max_risk_indicative=None)
    with pytest.raises(registry.RegistryError, match="never later"):
        registry.register_structure(world["path"], day=date(2027, 1, 5), symbol="NIFTY", expiry="x", spec_hash="other", now=at(), outcome="no_trade", structure=None, direction=None, legs=[], max_risk_indicative=None)


@pytest.mark.unit
def test_no_trade_is_recorded_and_makes_no_entry_or_chain_fetch(world):
    r = {"symbol": "NIFTY", "expiry": "x", "plan": {"strategy": "no_trade", "legs": []}, "priced": None}
    assert _record(world, r)["outcome"] == "no_trade"
    assert world["order"] == [] and len(registry.read(world["path"])) == 1


@pytest.mark.unit
def test_a_trade_with_no_quote_at_entry_is_void(world, monkeypatch):
    from webapp import strategist as st

    monkeypatch.setattr(st, "price", lambda *a: {"legs": [{"bid": 0, "ask": 5.0}]})
    _record(world)
    entry = registry.read(world["path"])[1]
    assert entry["status"] == "void"


@pytest.mark.unit
def test_a_trade_row_must_carry_every_required_field(tmp_path):
    with pytest.raises(registry.RegistryError, match="structure"):
        registry.register_structure(tmp_path / "r", day=MON, symbol="NIFTY", expiry="x", spec_hash="s", now=at(), outcome="trade", structure="long_call", direction="bullish", legs=[], max_risk_indicative=1.0)


@pytest.mark.unit
def test_the_spec_is_frozen_and_pins_the_prompt_in_use(tmp_path):
    spec = ai_test.read_spec()
    assert spec["version"]["prompt_sha256"] == ai_test.prompt_fingerprint()     # a changed prompt fails here: that is a new test
    assert spec["forward_test"]["report_minimum"] == 50 and spec["forward_test"]["verdict_count"] > 50
    assert spec["forward_test"]["backtest_of_the_llm"] == "not allowed: training-data leakage"
    p = tmp_path / "s.json"
    p.write_text(ai_test.SPEC_FILE.read_text(encoding="utf-8").replace('"version":', '"Version":', 1), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        ai_test.read_spec(p)


@pytest.mark.unit
def test_the_plan_tab_labels_and_no_score_number():
    assert "UNTESTED, no evidence of edge" in APP and "cost model unverified" in APP
    for gone in ("Pulse score", "By Pulse score", "score-${", "e.score", "/100", "<th>Score</th>", "by_score", "Why the score"):
        assert gone not in APP, gone


@pytest.mark.unit
def test_the_ranked_text_has_no_score_number():
    src = (Path(ai_test.__file__).parent / "strategist.py").read_text(encoding="utf-8")
    assert "/100. Target" not in src and "Untested, no evidence of edge" in src


@pytest.mark.unit
def test_every_pnl_or_charges_display_carries_the_cost_label():
    for line in APP.splitlines():
        if any(w in line for w in ("before charges", "Charges a lot, in and out", "after charges")):
            assert "COST_NOTE" in line, line[:90]


def test_power_table_in_the_spec_is_complete():
    spec = json.loads(ai_test.SPEC_FILE.read_text(encoding="utf-8"))["power"]
    assert spec["false_pass_at_zero_edge_max"] < 0.05 and spec["pass_rate_by_edge"]["0.20"]["500"] > 0.8
