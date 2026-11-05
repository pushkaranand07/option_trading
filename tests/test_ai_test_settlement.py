"""Settlement, baselines and backup of the AI strategist's forward test, on synthetic rows only (docs/PA_50)."""

import hashlib
import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import pytz

from tradingagents.research import ai_settle as s, registry

ROOT = Path(__file__).resolve().parents[1]
IST = pytz.timezone("Asia/Kolkata")
SPEC = "ab" * 32


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _chain():
    rows = []
    for k in range(900, 1101, 10):
        ce, pe = max(1000 - k, 0) + 20.0, max(k - 1000, 0) + 20.0
        rows.append({"strike": float(k), "ce": {"bid": ce - 1, "ask": ce + 1}, "pe": {"bid": pe - 1, "ask": pe + 1}})
    return {"spot": 1000.0, "lot": 10, "rows": rows}


def _save_chain(folder, chain):
    folder.mkdir(exist_ok=True)
    text = json.dumps(chain, sort_keys=True)
    sha = hashlib.sha256(text.encode()).hexdigest()
    (folder / f"{sha}.json").write_text(text, encoding="utf-8")
    return sha


LONG_CALL = [{"action": "BUY", "type": "CE", "strike": 1000.0, "price": 21.0}]


def _trade(path, chains, day, expiry="2027-01-07", structure="long_call", legs=None, symbol=s.SYNTHETIC, direction="bullish", pick=True):
    legs = legs or LONG_CALL
    now = IST.localize(datetime(day.year, day.month, day.day, 10))
    row = registry.register_structure(path, day=day, symbol=symbol, expiry=expiry, spec_hash=SPEC, now=now, outcome="trade", structure=structure, direction=direction, legs=legs, max_risk_indicative=210.0)
    rule = {"legs": [{"action": "BUY", "type": "PE", "strike": 1000.0, "price": 21.0}], "max_risk": 210.0, "charges": 0.0} if pick else None
    registry.record_entry(path, registration=row["hash"], now=now + timedelta(minutes=1), status="entered", legs=legs, lot=10, max_risk=s.max_risk(legs, 10), charges=5.0, chain_sha256=_save_chain(chains, _chain()), rule_pick=rule, spot=1000.0, net_per_unit=-21.0)
    return row


@pytest.mark.unit
def test_net_percent_is_after_charges_on_max_risk():
    assert s.net_percent(LONG_CALL, 1050.0, 10, 5.0, 210.0) == pytest.approx((29 * 10 - 5) / 210 * 100)        # 50 intrinsic less 21 paid
    assert s.net_percent(LONG_CALL, 900.0, 10, 5.0, 210.0) == pytest.approx((-210 - 5) / 210 * 100)
    assert s.net_percent(LONG_CALL, 1000.0, 10, 0.0, 0.0) is None


@pytest.mark.unit
def test_a_credit_spread_settles_and_its_risk_is_width_less_credit():
    legs = [{"action": "BUY", "type": "PE", "strike": 900.0, "price": 5.0}, {"action": "SELL", "type": "PE", "strike": 950.0, "price": 15.0}]
    assert s.max_risk(legs, 10) == pytest.approx((50 - 10) * 10)
    assert s.net_percent(legs, 1000.0, 10, 0.0, 400.0) == pytest.approx(100 / 400 * 100)                         # both expire worthless: keeps the credit
    assert s.net_percent(legs, 800.0, 10, 0.0, 400.0) == pytest.approx(-100.0)                                    # full loss


@pytest.mark.unit
def test_the_mirror_is_the_opposite_direction_at_the_same_distance_priced_from_the_chain():
    legs = [{"action": "BUY", "type": "CE", "strike": 1000.0, "price": 21.0}, {"action": "SELL", "type": "CE", "strike": 1050.0, "price": 19.0}]
    same, mirror = s.random_variants("bull_call_spread", legs, _chain())
    assert [(x["type"], x["strike"], x["action"]) for x in mirror] == [("PE", 1000.0, "BUY"), ("PE", 950.0, "SELL")]
    assert mirror[0]["price"] == 21.0 and mirror[1]["price"] == 19.0      # buy at the ask, sell at the bid
    assert same[1]["strike"] == 1050.0


@pytest.mark.unit
def test_a_condor_moves_its_centre_by_1_percent_and_keeps_its_wings():
    legs = [{"action": "BUY", "type": "PE", "strike": 950.0, "price": 1.0}, {"action": "SELL", "type": "PE", "strike": 970.0, "price": 1.0}, {"action": "SELL", "type": "CE", "strike": 1030.0, "price": 1.0}, {"action": "BUY", "type": "CE", "strike": 1050.0, "price": 1.0}]
    up, down = s.random_variants("iron_condor", legs, _chain())
    assert [x["strike"] for x in up] == [960.0, 980.0, 1040.0, 1060.0] and [x["strike"] for x in down] == [940.0, 960.0, 1020.0, 1040.0]


@pytest.mark.unit
def test_a_variant_with_no_two_sided_quote_is_left_out():
    chain = _chain()
    next(r for r in chain["rows"] if r["strike"] == 1000.0)["pe"]["bid"] = 0
    assert len(s.random_variants("long_call", LONG_CALL, chain)) == 1


def _world(tmp_path):
    return tmp_path / "r.jsonl", tmp_path / "chains"


@pytest.mark.unit
def test_every_outcome_is_counted_and_only_passed_expiries_settle(tmp_path):
    path, chains = _world(tmp_path)
    mon = date(2027, 1, 4)
    _trade(path, chains, mon)
    _trade(path, chains, mon + timedelta(days=1), expiry="28-Jan-2027", pick=False)
    now = IST.localize(datetime(2027, 1, 6, 10))
    registry.register_structure(path, day=date(2027, 1, 6), symbol=s.SYNTHETIC, expiry="x", spec_hash=SPEC, now=now, outcome="no_trade", structure=None, direction=None, legs=[], max_risk_indicative=None)
    row = registry.register_structure(path, day=date(2027, 1, 7), symbol=s.SYNTHETIC, expiry="2027-01-07", spec_hash=SPEC, now=IST.localize(datetime(2027, 1, 7, 10)), outcome="trade", structure="long_call", direction="bullish", legs=LONG_CALL, max_risk_indicative=1.0)
    registry.record_entry(path, registration=row["hash"], now=IST.localize(datetime(2027, 1, 7, 10, 1)), status="void", reason="no quote")
    registry.record_missed(path, day=date(2027, 1, 8), spec_hash=SPEC, now=now, reason="no question")
    registry.record_missed(path, day=date(2027, 1, 11), spec_hash=SPEC, now=now, reason="no question")   # a holiday
    out = s.settle(path, chains, {date(2027, 1, 7): 1050.0}, {date(2027, 1, 8)}, SPEC)
    c = out["counts"]
    assert (c["registered"], c["trade"], c["no_trade"], c["void"], c["open"], c["missed"], c["missed_on_non_sessions_dropped"]) == (4, 3, 1, 1, 1, 1, 1)
    assert len(out["settled"]) == 1 and out["settled"][0]["pct"] == pytest.approx((29 * 10 - 5) / 210 * 100)
    assert len(out["settled"][0]["random"]) == 2 and out["settled"][0]["rule"] is not None


@pytest.mark.unit
@pytest.mark.parametrize("real", [True, False], ids=["real_symbol", "synthetic"])
def test_real_rows_are_refused_wherever_the_file_is(tmp_path, real):
    path, chains = _world(tmp_path)
    _trade(path, chains, date(2027, 1, 4), symbol="NIFTY" if real else s.SYNTHETIC)
    if real:
        with pytest.raises(s.RealRowsRefused):
            s.settle(path, chains, {}, set(), SPEC)
    else:
        assert s.settle(path, chains, {}, set(), SPEC)["counts"]["trade"] == 1


@pytest.mark.unit
def test_the_script_is_not_cleared_and_refuses_the_real_registry(tmp_path):
    m = _script("ai_test_settle")
    assert m.REAL_RUN_APPROVED is False and m.REAL_INTERIM_APPROVED is True   # since 2026-11-05: the interim count only
    with pytest.raises(s.RealRowsRefused):                                  # settling the real registry stays refused
        m.run(m.REAL_REGISTRY, tmp_path, {}, set(), SPEC, mode="stop")


@pytest.mark.unit
def test_an_edited_row_or_changed_chain_stops_settlement(tmp_path):
    path, chains = _world(tmp_path)
    _trade(path, chains, date(2027, 1, 4))
    next(chains.glob("*.json")).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        s.settle(path, chains, {date(2027, 1, 7): 1000.0}, set(), SPEC)
    path.write_text(path.read_text(encoding="utf-8").replace("long_call", "long_put"), encoding="utf-8")
    with pytest.raises(registry.RegistryError):
        s.settle(path, chains, {date(2027, 1, 7): 1000.0}, set(), SPEC)


@pytest.mark.unit
def test_another_versions_rows_are_ignored(tmp_path):
    path, chains = _world(tmp_path)
    _trade(path, chains, date(2027, 1, 4))
    assert s.settle(path, chains, {}, set(), "cd" * 32)["counts"]["registered"] == 0


def _rows(n, edge, seed=0, spread=2.0):
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        move = rng.normal(0, 30)
        out.append({"date": f"d{i}", "expiry": f"2027-W{i // 5:03d}", "pct": edge + move + rng.normal(0, spread), "random": [move, -move], "rule": rng.normal(0, 30)})
    return out


@pytest.mark.unit
def test_nothing_is_reported_below_50():
    r = s.evaluate(_rows(49, 50.0), SPEC)
    assert r == {"status": "below minimum: nothing is reported", "settled": 49, "report_minimum": 50}


@pytest.mark.unit
@pytest.mark.parametrize("n", [50, 499])
def test_between_50_and_500_numbers_carry_the_warning_and_no_verdict(n):
    r = s.evaluate(_rows(n, 50.0), SPEC)
    assert r["status"] == "reported, no verdict" and "too few" in r["warning"] and "verdict" not in r and "checks" not in r
    assert "cost model unverified" in r["label"]


@pytest.mark.unit
def test_a_planted_large_edge_passes_and_no_edge_fails_at_500():
    good = s.evaluate(_rows(500, 30.0), SPEC)
    assert good["status"] == "verdict" and good["verdict"] == "pass" and all(good["checks"].values())
    none = s.evaluate(_rows(500, 0.0, seed=3), SPEC)
    assert none["verdict"] == "fail" and "not ruled out" in none["meaning_if_fail"]


@pytest.mark.unit
def test_only_the_first_500_decide():
    base = _rows(500, 30.0)
    later = base + [{"date": f"x{i}", "expiry": "2030-W001", "pct": -1000.0, "random": [0.0, 0.0], "rule": 0.0} for i in range(100)]
    a, b = s.evaluate(base, SPEC), s.evaluate(later, SPEC)
    assert b["used"] == 500 and b["verdict"] == a["verdict"] and b["mean_net_pct_of_max_risk"] == a["mean_net_pct_of_max_risk"]


@pytest.mark.unit
def test_losing_to_the_rule_pick_or_having_none_fails():
    rows = _rows(500, 30.0)
    assert s.evaluate([{**x, "rule": x["pct"] + 5} for x in rows], SPEC)["checks"]["above_rule_pick"] is False
    assert s.evaluate([{**x, "rule": None} for x in rows], SPEC)["verdict"] == "fail"


@pytest.mark.unit
def test_results_repeat_from_the_same_spec_hash():
    rows = _rows(100, 5.0)
    assert s.evaluate(rows, SPEC) == s.evaluate(rows, SPEC)


def _source(tmp_path):
    src = tmp_path / "ai_test"
    (src / "chains").mkdir(parents=True)
    (src / "registry.jsonl").write_text("row\n", encoding="utf-8")
    (src / "chains" / "a.json").write_text("{}", encoding="utf-8")
    return src


@pytest.mark.unit
def test_a_backup_is_dated_checksummed_and_verifies(tmp_path):
    m = _script("ai_test_backup")
    dest = tmp_path / "d"
    dest.mkdir()
    target = m.backup(dest, _source(tmp_path), tmp_path / "repo", datetime(2027, 1, 4, 10))
    assert target.name == "ai_test_backup_20270104_100000" and (target / "chains" / "a.json").exists() and m.verify(target) == []
    assert "registry.jsonl" in (target / m.SUMS).read_text(encoding="utf-8")


@pytest.mark.unit
def test_verify_catches_changed_missing_and_extra_files(tmp_path):
    m = _script("ai_test_backup")
    dest = tmp_path / "d"
    dest.mkdir()
    t = m.backup(dest, _source(tmp_path), tmp_path / "repo")
    (t / "registry.jsonl").write_text("edited\n", encoding="utf-8")
    (t / "chains" / "a.json").unlink()
    (t / "extra.txt").write_text("x", encoding="utf-8")
    p = " ".join(m.verify(t))
    assert "changed: registry.jsonl" in p and "missing: chains/a.json" in p and "not in the checksum file: extra.txt" in p


@pytest.mark.unit
def test_a_backup_refuses_the_repo_and_never_overwrites(tmp_path):
    m = _script("ai_test_backup")
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    src = _source(tmp_path)
    for bad in (repo, repo / "sub"):
        with pytest.raises(ValueError, match="outside the repo"):
            m.backup(bad, src, repo)
    dest = tmp_path / "d"
    dest.mkdir()
    when = datetime(2027, 1, 4)
    m.backup(dest, src, repo, when)
    with pytest.raises(FileExistsError):
        m.backup(dest, src, repo, when)


@pytest.mark.unit
def test_the_backup_has_no_network_or_schedule():
    text = (ROOT / "scripts" / "ai_test_backup.py").read_text(encoding="utf-8")
    for word in ("requests", "urllib", "schtasks", "boto", "http"):
        assert word not in text, word


STOP = date(2027, 11, 1)
TRIALS = ["trial_a", "trial_b"]


@pytest.mark.unit
def test_no_performance_is_read_before_the_stop_date():
    with pytest.raises(ValueError, match="before the stop date"):
        s.at_stop(_rows(100, 50.0), SPEC, date(2027, 10, 31), STOP, TRIALS)


@pytest.mark.unit
def test_a_lower_bound_below_zero_retires_the_test_in_the_written_words():
    r = s.at_stop(_rows(200, -20.0), SPEC, STOP, STOP, TRIALS)
    assert r["lower_bound_pct"] < 0 and r["action"] == "retire the test" and r["statement"] == "no large edge detected"


@pytest.mark.unit
def test_a_lower_bound_above_zero_under_500_goes_to_a_written_decision_with_the_trial_list():
    r = s.at_stop(_rows(200, 40.0), SPEC, STOP, STOP, TRIALS)
    assert r["lower_bound_pct"] > 0 and "in writing" in r["action"] and r["trial_list"] == TRIALS and "statement" not in r


@pytest.mark.unit
def test_fewer_than_50_at_the_stop_reports_nothing_and_goes_to_a_written_decision():
    r = s.at_stop(_rows(49, 40.0), SPEC, STOP, STOP, TRIALS)
    assert "in writing" in r["action"] and "mean_net_pct_of_max_risk" not in r and r["trial_list"] == TRIALS


@pytest.mark.unit
def test_the_interim_check_shows_counts_and_missed_days_only(tmp_path):
    path, chains = _world(tmp_path)
    _trade(path, chains, date(2027, 1, 4))
    registry.record_missed(path, day=date(2027, 1, 5), spec_hash=SPEC, now=IST.localize(datetime(2027, 1, 6, 10)), reason="none")
    r = s.interim_counts(path, SPEC, {date(2027, 1, 5)})
    assert r["questions"] == 1 and r["entered"] == 1 and r["missed_days"] == ["2027-01-05"]
    assert not {"pct", "mean_net_pct_of_max_risk", "lower_bound_pct", "settled"} & set(r)


@pytest.mark.unit
def test_the_interim_check_refuses_real_rows_until_approved(tmp_path):
    path, chains = _world(tmp_path)
    _trade(path, chains, date(2027, 1, 4), symbol="NIFTY")
    with pytest.raises(s.RealRowsRefused):
        s.interim_counts(path, SPEC, set())
