"""Gate v2: the action-list skip rule, distinct-date counts, tiers, thresholds (docs/gate_v2.json, docs/PA_40)."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.research import gate as g, gate2 as g2, loader


def _sessions(n=60):
    out, d = [], date(2020, 1, 1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _bonus_futures(s, at=10):
    far = s[-1] + timedelta(days=30)
    rows = []
    for i, d in enumerate(s):
        px, oi = (100.0, 1000.0) if i < at else (50.0, 2000.0)
        rows.append({"trade_date": d, "symbol": "AAA", "instrument": "FUTSTK", "expiry": far, "open": px, "high": px, "low": px, "close": px,
                     "settle": px, "open_interest": oi, "oi_change": 0.0, "contracts": 10.0, "turnover": 1.0})
    return g.clean_futures(pd.DataFrame(rows))


@pytest.mark.unit
def test_v2_is_frozen_and_v1_is_untouched(tmp_path):
    spec = g2.read_spec()
    assert spec["skip_rule"]["gate_uses"] == "A"
    assert g.read_spec()["version"] == 1
    changed = tmp_path / "g.json"
    changed.write_text(g2.GATE_FILE.read_text(encoding="utf-8").replace('"gate_uses": "A"', '"gate_uses": "B"'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        g2.read_spec(changed)


@pytest.mark.unit
def test_rule_a_uses_the_list_and_not_the_price_move():
    s = _sessions()
    f = _bonus_futures(s)
    listed = pd.DataFrame({"symbol": ["AAA"], "ex_date": [s[10]], "kind": ["bonus"]})
    empty = listed.iloc[0:0]
    ev, r = g2.prepare(f, listed, "A")
    assert g.build_trades(f, 3, s, ev)["gross"].abs().max() == 0.0 and r["ret"].abs().max() == 0.0
    ev, _ = g2.prepare(f, empty, "A")              # not on the list: rule A keeps the trade, even with a visible footprint
    assert g.build_trades(f, 3, s, ev)["gross"].min() == -0.5
    ev, _ = g2.prepare(f, empty, "B")              # rule B, report only, removes it
    assert g.build_trades(f, 3, s, ev)["gross"].abs().max() == 0.0


@pytest.mark.unit
def test_an_ex_date_on_the_entry_session_does_not_skip_the_trade():
    s = _sessions()
    f = _bonus_futures(s)
    ev = g2.action_events(pd.DataFrame({"symbol": ["AAA"], "ex_date": [s[10]]}))
    t = g.build_trades(f, 3, s, ev)
    assert s[10] in set(t["entry"]) and s[11] in set(t["entry"])     # the open at entry is already adjusted
    assert s[9] not in set(t["entry"]) and s[8] not in set(t["entry"])


@pytest.mark.unit
def test_a_trade_is_labelled_no_action_list_unless_every_month_has_a_file():
    t = pd.DataFrame({"entry": [date(2014, 6, 2), date(2016, 3, 1), date(2016, 3, 30), date(2015, 1, 5)],
                      "exit": [date(2014, 6, 5), date(2016, 3, 5), date(2016, 4, 2), date(2015, 1, 8)]})
    out = g2.label_action_list(t, {"2016-03"})
    assert list(out["has_action_list"]) == [False, True, False, False]


@pytest.mark.unit
def test_the_loader_refuses_actions_in_a_locked_period(tmp_path):
    with pytest.raises(loader.HoldoutLocked):
        loader.load_actions(end=date(2025, 1, 1), root=tmp_path)


def _eval(forward=None, wf=None, base=None, u2=0.01, block=2):
    rng = np.random.default_rng(0)
    if forward is None:
        d = np.arange(200)
        win = rng.random(200) < 0.7
        forward = {"date": d, "net": np.where(win, 0.02, -0.01), "win_null": np.full(200, 0.45)}
    if wf is None:
        arr = np.array([(i, j) for i in range(6) for j in range(150)])
        wf = {"fold": arr[:, 0], "date": arr[:, 0] * 10000 + arr[:, 1], "net": np.full(900, 0.01), "n_folds": 6}
    return g2.evaluate(forward, wf, base if base is not None else {"always_long": 0.0}, u2, 5, 0.0044, block, rng, reps=300)


@pytest.mark.unit
def test_effective_trades_are_distinct_signal_dates():
    d = np.repeat(np.arange(99), 50)         # 4,950 raw trades on 99 dates
    net = np.random.default_rng(0).normal(0.01, 0.01, len(d))
    r = _eval(forward={"date": d, "net": net, "win_null": np.full(len(d), 0.45)})
    assert r["a"]["raw"] == 4950 and r["a"]["distinct_dates"] == 99 and not r["a"]["pass"]


@pytest.mark.unit
def test_tier_1_can_pass_while_tier_2_fails_on_win_rate():
    rng = np.random.default_rng(1)
    d = np.arange(400)
    win = rng.random(400) < 0.55
    r = _eval(forward={"date": d, "net": np.where(win, 0.03, -0.01), "win_null": np.full(400, 0.40)})
    assert r["tier1"] and not r["b"]["pass"] and not r["tier2"]


@pytest.mark.unit
def test_both_tiers_pass_on_a_strong_model_and_each_tier1_item_blocks_both():
    assert _eval()["tier1"] and _eval()["tier2"]
    r = _eval(base={"always_long": 10.0})
    assert not r["tier1"] and not r["tier2"]
    thin = np.array([(i, j) for i in range(6) for j in range(50)])
    r = _eval(wf={"fold": thin[:, 0], "date": thin[:, 0] * 10000 + thin[:, 1], "net": np.full(300, 0.01), "n_folds": 6})
    assert not r["g"]["pass"]                # 50 dates a fold


@pytest.mark.unit
def test_item_d_uses_the_block_and_fails_without_enough_dates():
    d, net = np.arange(5), np.full(5, 0.01)
    r = _eval(forward={"date": d, "net": net, "win_null": np.full(5, 0.4)}, block=10)
    assert not r["d"]["pass"]


@pytest.mark.unit
def test_winsorizing_is_report_only_and_clips_the_tails():
    v = np.r_[np.zeros(998), -1.0, 1.0]
    assert g2.winsorized_mean(v) == pytest.approx(0.0, abs=1e-9)
    assert g2.winsorized_mean(np.array([])) != g2.winsorized_mean(np.array([]))     # nan
    assert "winsorized" not in Path(g2.__file__).read_text(encoding="utf-8").split("def evaluate")[1]


@pytest.mark.unit
def test_binomial_requirements():
    assert g2.binomial_requirement(0.5, 0.05, 100) == 59
    assert g2.binomial_trades_needed(0.5, 0.05, 0.60) is not None
    assert g2.binomial_trades_needed(0.6, 0.05, 0.60) is None


@pytest.mark.unit
def test_the_addendum_is_frozen_and_names_the_gate_it_applies_to(tmp_path):
    spec = g2.read_addendum()
    assert spec["gate_v2_sha256"] == g2.GATE_SHA256 and not spec["edits_gate_files"]
    changed = tmp_path / "a.json"
    changed.write_text(g2.ADDENDUM_FILE.read_text(encoding="utf-8").replace('"addendum": 1', '"addendum": 2'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        g2.read_addendum(changed)


@pytest.mark.unit
def test_addendum_2_is_frozen_records_the_timing_counts_and_leaves_item_g_open(tmp_path):
    from tradingagents.research import features as fx

    spec = g2.read_addendum_2()
    assert spec["gate_v2_sha256"] == g2.GATE_SHA256 and spec["addendum_1_sha256"] == g2.ADDENDUM_SHA256 and spec["features_v1_sha256"] == fx.SPEC_SHA256
    timing = spec["decision_2_timing"]
    public = timing["public_by_close_of_d"]["features"]
    all_features = fx.read_spec()["features"]
    assert set(public) == {n for n, f in all_features.items() if f["family"] == "g"}
    assert len(public) + timing["stay_at_d_minus_1"]["feature_count"] == len(all_features)
    assert sum(len(v) for v in timing["stay_at_d_minus_1"]["raw_fields"].values()) == timing["stay_at_d_minus_1"]["raw_field_count"]
    assert spec["decision_3_item_g"]["chosen"] is None
    changed = tmp_path / "a.json"
    changed.write_text(g2.ADDENDUM_2_FILE.read_text(encoding="utf-8").replace('"chosen": null', '"chosen": "a"'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        g2.read_addendum_2(changed)


@pytest.mark.unit
def test_addendum_3_is_frozen_and_consistent(tmp_path):
    from tradingagents.research import features as fx

    spec = g2.read_addendum_3()
    assert spec["addendum_2_sha256"] == g2.ADDENDUM_2_SHA256 and spec["features_v1_sha256"] == fx.SPEC_SHA256
    assert "".join(spec["pass_condition"]["items"]) == g2.PASS_ITEMS
    item_g = spec["item_g"]
    inputs = {n for n, f in fx.read_spec()["features"].items() if f["role"] == "input"}
    assert set().union(*item_g["allowed_features_per_fold"].values()) <= inputs
    assert item_g["features_that_can_go_forward"] + len(item_g["features_in_fewer_than_4_folds_cannot_go_forward"]) == len(inputs)
    changed = tmp_path / "a.json"
    changed.write_text(g2.ADDENDUM_3_FILE.read_text(encoding="utf-8").replace('"addendum": 3', '"addendum": 4'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        g2.read_addendum_3(changed)


@pytest.mark.unit
def test_a_baseline_on_d_minus_1_ignores_the_signal_days_own_return():
    s = _sessions(12)
    r = pd.DataFrame({"symbol": "AAA", "trade_date": s[:10], "ret": [0.01, -0.02, 0.03, 0.01, 0.02, -0.01, 0.02, 0.01, -0.03, 0.04]})
    trades = pd.DataFrame({"symbol": ["AAA"], "signal": [s[7]]})
    lag = g2.lag_one_session(r, s, "trade_date")
    assert g.signals_baseline("prev_day", trades, lag).iloc[0] == 1          # s[6] rose
    changed = r.assign(ret=lambda x: x["ret"].where(x["trade_date"] != s[7], -0.5))
    assert g.signals_baseline("prev_day", trades, g2.lag_one_session(changed, s, "trade_date")).iloc[0] == 1
    assert g.signals_baseline("prev_day", trades, changed).iloc[0] == -1     # the old timing reads D itself


@pytest.mark.unit
def test_a_signal_after_a_hole_has_no_lagged_value():
    s = _sessions(6)
    r = pd.DataFrame({"symbol": "AAA", "trade_date": [s[0], s[1], s[3]], "ret": [0.01, 0.01, 0.01]})     # s[2] is a hole
    lag = g2.lag_one_session(r, s, "trade_date")
    assert s[3] not in set(lag["trade_date"]) and list(lag["trade_date"]) == [s[1], s[2], s[4]]


@pytest.mark.unit
def test_the_pass_ignores_items_b_and_c():
    items = {i: {"pass": True} for i in "abcdefg"}
    assert g2.passes({**items, "b": {"pass": False}, "c": {"pass": False}})
    for i in "adefg":
        assert not g2.passes({**items, i: {"pass": False}}), i


@pytest.mark.unit
def test_forward_skip_uses_only_the_list_at_signal_time():
    listed = pd.DataFrame({"symbol": ["AAA", "AAA", "BBB"], "ex_date": [date(2027, 1, 8), date(2027, 1, 5), date(2027, 1, 8)],
                           "kind": ["bonus", "split", "scheme"]})
    entry, exit_day = date(2027, 1, 5), date(2027, 1, 8)
    assert g2.forward_skip(listed, "AAA", entry, exit_day)                     # on the list, inside the window
    assert not g2.forward_skip(listed.iloc[1:], "AAA", entry, exit_day)        # ex-date on the entry session: not inside
    assert not g2.forward_skip(listed, "CCC", entry, exit_day)                 # not on the list: the trade counts as normal
    assert not g2.forward_skip(listed, "BBB", entry, exit_day)                 # not one of rule A's kinds


@pytest.mark.unit
def test_the_action_list_hash_changes_with_the_file(tmp_path):
    p = tmp_path / "list.csv"
    p.write_text("a", encoding="utf-8")
    first = g2.action_list_sha256(p)
    p.write_text("b", encoding="utf-8")
    assert len(first) == 64 and g2.action_list_sha256(p) != first


@pytest.mark.unit
def test_the_time_shift_moves_whole_dates_with_no_overlap():
    import sys
    sys.path.insert(0, str(Path(g.ROOT, "scripts")))
    import research_gate2_harness as h2

    labels = np.array([0, 0, 1, 2, 2, 2, 3, 4, 4])
    out = h2.shift_dates(labels, labels, 2)
    assert list(out) == [3, 3, 4, 0, 0, 0, 1, 2, 2]     # every row reads the date 2 earlier, circularly


@pytest.mark.unit
def test_the_v2_code_holds_no_unlock():
    for rel in ("tradingagents/research/gate2.py", "scripts/research_gate2_harness.py"):
        assert "Unlock(" not in Path(g.ROOT, rel).read_text(encoding="utf-8"), rel
