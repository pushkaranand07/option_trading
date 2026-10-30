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
def test_the_v2_code_holds_no_unlock():
    for rel in ("tradingagents/research/gate2.py", "scripts/research_gate2_harness.py"):
        assert "Unlock(" not in Path(g.ROOT, rel).read_text(encoding="utf-8"), rel
