"""Gate v1: trade rules, roll gap, look-ahead, holdout refusal, gate items, registry (docs/gate_v1.json, docs/PA_39)."""

import os
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import pytz

from tradingagents.analytics import trial_log
from tradingagents.research import gate as g, loader, registry

IST = pytz.timezone("Asia/Kolkata")


def _sessions(start=date(2020, 1, 1), n=60):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _futures(sessions, near_jump=0.0):
    """Two contracts on one symbol: the far contract trades 100 points above the near one (a large roll gap)."""
    rows = []
    near, far = sessions[20], sessions[-1] + timedelta(days=30)
    for i, d in enumerate(sessions):
        px = 100.0 + i
        if d <= near:
            rows.append({"trade_date": d, "symbol": "AAA", "instrument": "FUTSTK", "expiry": near, "open": px, "high": px,
                         "low": px, "close": px + near_jump, "settle": px, "open_interest": 1000.0, "oi_change": 0.0,
                         "contracts": 10.0, "turnover": 1.0})
        rows.append({"trade_date": d, "symbol": "AAA", "instrument": "FUTSTK", "expiry": far, "open": px + 100, "high": px + 100,
                     "low": px + 100, "close": px + 100, "settle": px + 100, "open_interest": 1000.0, "oi_change": 0.0,
                     "contracts": 10.0, "turnover": 1.0})
    return g.clean_futures(pd.DataFrame(rows))


# ---- gate file

@pytest.mark.unit
def test_gate_file_is_frozen_and_changes_are_refused(tmp_path):
    spec = g.read_spec()
    assert spec["gate"]["g"]["x_h_percent"] == {"1": 0.16, "2": 0.28, "3": 0.34, "5": 0.44, "10": 0.63}
    assert spec["costs"]["gate_at"] == 1.5
    changed = tmp_path / "gate.json"
    changed.write_text(g.GATE_FILE.read_text(encoding="utf-8").replace('"b": "win rate >= 60%"', '"b": "win rate >= 50%"'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        g.read_spec(changed)


# ---- step 6.5: the roll gap

@pytest.mark.unit
def test_a_roll_is_never_counted_as_profit():
    s = _sessions()
    f = _futures(s)
    r = g.daily_returns(f)
    assert r["ret"].abs().max() < 0.02                       # the 100-point gap between contracts never appears
    t = g.build_trades(f, 5, s)
    assert len(t) and t["gross"].abs().max() < 0.10
    assert t.groupby(["symbol", "entry"])["expiry"].nunique().max() == 1
    # the trade picks a contract that outlives its exit
    assert (pd.to_datetime(t["expiry"]) >= pd.to_datetime(t["exit"])).all()


# ---- trade rules

@pytest.mark.unit
def test_entry_is_the_next_open_and_exit_the_close_h_sessions_after_the_signal():
    s = _sessions()
    f = _futures(s)
    t = g.build_trades(f, 3, s)
    row = t[t["signal"] == s[0]].iloc[0]
    assert row["entry"] == s[1] and row["exit"] == s[3]
    assert row["e_open"] == 101.0 and row["x_price"] == 103.0
    one = g.build_trades(f, 1, s)
    r1 = one[one["signal"] == s[0]].iloc[0]
    assert r1["entry"] == r1["exit"] == s[1]


@pytest.mark.unit
def test_only_one_open_trade_per_underlying_and_later_signals_are_ignored():
    s = _sessions()
    t = g.build_trades(_futures(s), 5, s)
    kept = g.one_open_trade(t).sort_values("entry")
    assert (kept["entry"].to_numpy()[1:] > kept["exit"].to_numpy()[:-1]).all()
    assert list(kept["signal"])[:2] == [s[0], s[5]]


@pytest.mark.unit
def test_a_zero_net_trade_is_not_a_win():
    t = pd.DataFrame({"gross": [g.round_trip_cost("stock", 1.5)], "kind": ["stock"]})
    net = g.net_returns(t, [1], 1.5)
    assert abs(net[0]) < 1e-12 and not (np.round(net, 12) > 0).any()


@pytest.mark.unit
def test_a_trade_spanning_a_split_is_not_taken_and_the_price_is_not_adjusted():
    s = _sessions()
    rows = []
    far = s[-1] + timedelta(days=30)
    for i, d in enumerate(s):
        px, oi = (100.0, 1000.0) if i < 10 else (50.0, 2000.0)         # 1:1 bonus at session 10
        rows.append({"trade_date": d, "symbol": "AAA", "instrument": "FUTSTK", "expiry": far, "open": px, "high": px, "low": px,
                     "close": px, "settle": px, "open_interest": oi, "oi_change": 0.0, "contracts": 10.0, "turnover": 1.0})
    f = g.clean_futures(pd.DataFrame(rows))
    ev = g.split_events(f)
    assert list(ev["trade_date"]) == [s[10]]
    assert g.build_trades(f, 3, s)["gross"].min() == -0.5           # unscreened: the fake loss
    t = g.build_trades(f, 3, s, ev)
    assert t["gross"].abs().max() == 0.0
    assert g.daily_returns(f, ev)["ret"].abs().max() == 0.0
    assert f["close"].min() == 50.0                                 # nothing adjusted


@pytest.mark.unit
def test_costs_scale_with_the_multiple_and_differ_by_class():
    assert abs(g.round_trip_cost("stock") - 0.001613) < 2e-6 and abs(g.round_trip_cost("index") - 0.001013) < 2e-6
    assert g.round_trip_cost("stock", 1.5) == pytest.approx(1.5 * g.round_trip_cost("stock"))


# ---- step 6.4 and targets: look-ahead

@pytest.mark.unit
def test_truncating_at_d_leaves_features_and_signals_for_d_unchanged():
    s = _sessions()
    f = _futures(s)
    full_r = g.daily_returns(f)
    for d in (s[25], s[30], s[40]):
        cut = f[f["trade_date"] <= d]
        cut_r = g.daily_returns(cut)
        a, b = full_r[full_r["trade_date"] <= d].reset_index(drop=True), cut_r.reset_index(drop=True)
        pd.testing.assert_frame_equal(a, b)
        fm, cm = g.expected_move(full_r, 5), g.expected_move(cut_r, 5)
        pd.testing.assert_frame_equal(fm[fm["signal"] == d].reset_index(drop=True), cm[cm["signal"] == d].reset_index(drop=True))
        probe = pd.DataFrame({"symbol": ["AAA"], "signal": [d]})
        for name in ("prev_day", "momentum_5d", "always_long", "always_short"):
            assert g.signals_baseline(name, probe, full_r).tolist() == g.signals_baseline(name, probe, cut_r).tolist()


@pytest.mark.unit
def test_a_label_for_d_uses_no_data_after_d_plus_h():
    s = _sessions()
    f = _futures(s)
    h, d = 5, s[25]
    trades = g.build_trades(f, h, s)
    row = trades[trades["signal"] == d]
    r = g.daily_returns(f)
    full = g.targets(row, r, h, s)
    # scramble everything after D + h: labels must not move
    after = f.copy()
    late = after["trade_date"] > s[25 + h]
    after.loc[late, ["open", "close", "settle"]] *= 3.0
    t2 = g.build_trades(after, h, s)
    again = g.targets(t2[t2["signal"] == d], g.daily_returns(after), h, s)
    pd.testing.assert_frame_equal(full.reset_index(drop=True), again.reset_index(drop=True))
    # and something inside the window does move it
    inside = f.copy()
    inside.loc[inside["trade_date"] == s[25 + h], ["close"]] *= 1.5
    t3 = g.targets(g.build_trades(inside, h, s).query("signal == @d"), g.daily_returns(inside), h, s)
    assert t3["t2_long"].iloc[0] != full["t2_long"].iloc[0]


@pytest.mark.unit
def test_t3_is_risk_only_and_t1_follows_t2():
    s = _sessions()
    f = _futures(s)
    t = g.targets(g.build_trades(f, 5, s), g.daily_returns(f), 5, s).dropna(subset=["t3_vol"])
    assert (t["t3_vol"] >= 0).all() and (t["t1_long"] == (t["t2_long"] > 0)).all() and (t["t1_short"] == (t["t2_short"] > 0)).all()


# ---- step 6.6: the holdout

def _store(tmp_path):
    root = tmp_path / "store"
    (root / "base_futures").mkdir(parents=True)
    pd.DataFrame({"trade_date": [date(2024, 6, 3)], "known_from": [date(2024, 6, 4)], "symbol": ["AAA"]}).to_parquet(
        root / "base_futures" / "2024.parquet", index=False)
    return root


@pytest.mark.unit
@pytest.mark.parametrize("start, end", [(date(2024, 1, 1), date(2025, 1, 1)), (date(2026, 10, 27), date(2026, 10, 30))])
def test_any_read_of_the_locked_range_raises_and_the_attempt_is_logged(tmp_path, start, end):
    log = tmp_path / "t.sqlite"
    with pytest.raises(loader.HoldoutLocked):
        g.load("base_futures", start=start, end=end, root=_store(tmp_path), log_path=log)
    (event,) = trial_log.load_events("holdout_refused", path=log)
    assert event["detail"]["dataset"] == "base_futures"


@pytest.mark.unit
def test_live_tables_are_refused_and_logged(tmp_path):
    log = tmp_path / "t.sqlite"
    with pytest.raises(loader.LiveTableRefused):
        g.load("option_chain", root=_store(tmp_path), log_path=log)
    assert len(trial_log.load_events("holdout_refused", path=log)) == 1


@pytest.mark.unit
def test_the_default_read_stops_before_the_locked_range(tmp_path):
    df = g.load("base_futures", root=_store(tmp_path), log_path=tmp_path / "t.sqlite")
    assert len(df) == 1 and trial_log.load_events(path=tmp_path / "t.sqlite") == []


@pytest.mark.unit
def test_the_gate_code_holds_no_unlock():
    for rel in ("tradingagents/research/gate.py", "scripts/research_gate_harness.py"):
        assert "Unlock(" not in Path(g.ROOT, rel).read_text(encoding="utf-8"), rel


# ---- gate items

def _forward(n_dates=200, per=1, wr=0.7, edge=0.01, seed=0):
    rng = np.random.default_rng(seed)
    d = np.repeat(np.arange(n_dates), per)
    win = rng.random(len(d)) < wr
    net = np.where(win, edge * 2, -edge)
    return {"date": d, "net": net, "win_null": np.full(len(d), 0.45)}


def _wf(means, eff_per_fold=150):
    rows = [(i, j, m) for i, m in enumerate(means) for j in range(eff_per_fold)]
    arr = np.array(rows, dtype=float)
    return {"fold": arr[:, 0].astype(int), "date": arr[:, 0] * 10000 + arr[:, 1], "net": arr[:, 2], "n_folds": len(means)}


def _eval(forward=None, wf=None, base=None, u2=0.01, x=0.005, h=5):
    return g.evaluate(forward or _forward(), wf or _wf([0.01] * 6), base if base is not None else {"always_long": 0.0}, u2, h, x,
                      np.random.default_rng(0), reps=300)


@pytest.mark.unit
def test_a_strong_model_passes_every_item():
    r = _eval()
    assert r["passed"] and all(r[k]["pass"] for k in "abcdefg")


@pytest.mark.unit
def test_each_item_fails_on_its_own():
    assert not _eval(forward=_forward(n_dates=60))["a"]["pass"]                      # 60 trades
    assert not _eval(forward=_forward(wr=0.55))["b"]["pass"]
    high_null = _forward() | {"win_null": np.full(200, 0.72)}
    assert not _eval(forward=high_null)["c"]["pass"]                                 # null is the baseline, not 50%
    assert not _eval(forward=_forward(wr=0.30))["d"]["pass"]
    assert not _eval(base={"always_long": 10.0})["e"]["pass"]
    assert not _eval(base={})["e"]["pass"]
    assert not _eval(u2=-0.01)["f"]["pass"]
    assert not _eval(wf=_wf([0.01, 0.01, 0.01, 0.01, -0.001, -0.001]))["g"]["pass"]  # (i) 4 of 6 positive
    assert not _eval(wf=_wf([0.01] * 5 + [-0.01]))["g"]["pass"]                      # (ii) a fold below -X
    assert not _eval(wf=_wf([0.01] * 6, eff_per_fold=50))["g"]["pass"]               # (iii) a thin fold fails
    missing = _wf([0.01] * 5) | {"n_folds": 6}
    assert not _eval(wf=missing)["g"]["pass"]                                        # a skipped fold is a FAIL


@pytest.mark.unit
def test_same_date_signals_count_less_than_their_raw_number():
    rng = np.random.default_rng(0)
    d = np.repeat(np.arange(100), 20)
    common = np.repeat(rng.normal(0, 1, 100), 20)
    clustered = common + rng.normal(0, 0.2, 2000)
    independent = rng.normal(0, 1, 2000)
    assert g.effective_count(d, clustered) < 130
    assert g.effective_count(d, independent) > 1500
    assert g.effective_count(np.arange(150), rng.normal(0, 1, 150)) == 150


@pytest.mark.unit
def test_purge_and_embargo_leave_training_clear_of_test_folds():
    s = list(pd.bdate_range("2012-01-02", "2017-12-29").date)
    pos = list(range(0, len(s) - 6))
    entry = pd.Series([s[i] for i in pos])
    exit_ = pd.Series([s[i + 5] for i in pos])
    keep = g.train_mask(entry, exit_, 2, 5, s, folds=((2013, 2013), (2014, 2014), (2015, 2015)))
    first = next(d for d in s if d.year == 2015)
    assert (exit_[keep] < first).all()
    i0 = s.index(first)
    assert (exit_[keep].map(s.index) < i0 - 5).all()
    y14_end = s.index(next(d for d in s if d.year == 2015))
    y13_end = s.index(next(d for d in s if d.year == 2014))
    assert not entry[keep].map(s.index).between(y13_end, y13_end + 4).any()  # embargo after an earlier test fold
    assert not entry[keep].map(s.index).between(y14_end, y14_end + 4).any()


@pytest.mark.unit
def test_too_few_dates_for_an_interval_can_never_pass_item_d():
    d, net = np.arange(5), np.full(5, 0.01)
    assert g.block_bootstrap_lower(d, net, 10, np.random.default_rng(0)) == float("-inf")
    assert not _eval(forward={"date": d, "net": net, "win_null": np.full(5, 0.4)}, h=10)["d"]["pass"]


STORE = Path(os.environ.get("RESEARCH_STORE_DIR", "-"))


@pytest.mark.skipif(not (STORE / "base_futures").is_dir(), reason="set RESEARCH_STORE_DIR")
def test_real_data_truncated_at_d_leaves_features_and_signals_unchanged(tmp_path):
    log = tmp_path / "t.sqlite"
    fut = g.load("base_futures", start=date(2016, 1, 1), end=date(2017, 12, 31), symbols=["NIFTY", "RELIANCE"], root=STORE, log_path=log)
    f = g.clean_futures(fut)
    ev = g.split_events(f)
    full = g.daily_returns(f, ev)
    for d in (date(2016, 6, 1), date(2016, 12, 29), date(2017, 6, 30)):
        cut = f[f["trade_date"] <= d]
        r = g.daily_returns(cut, g.split_events(cut))
        pd.testing.assert_frame_equal(full[full["trade_date"] <= d].reset_index(drop=True), r.reset_index(drop=True))
        probe = pd.DataFrame({"symbol": ["NIFTY", "RELIANCE"], "signal": [d, d]})
        for name in ("prev_day", "momentum_5d"):
            assert g.signals_baseline(name, probe, full).tolist() == g.signals_baseline(name, probe, r).tolist()


# ---- step 7: the registry

def _sig(path, entry=date(2026, 11, 2), now=None, symbol="NIFTY", **kw):
    return registry.register(path, signal_date=date(2026, 10, 30), entry_date=entry, symbol=symbol, direction=1, spec_hash="abc",
                             universe="U1", horizon=5, now=now or IST.localize(datetime(2026, 10, 30, 20, 0)), **kw)


@pytest.mark.unit
def test_registry_chain_detects_any_edit(tmp_path):
    p = tmp_path / "r.jsonl"
    _sig(p)
    _sig(p, symbol="BANKNIFTY")
    assert registry.verify(p) == 2
    lines = p.read_text(encoding="utf-8").splitlines()
    p.write_text("\n".join([lines[0].replace('"direction": 1', '"direction": -1'), lines[1]]) + "\n", encoding="utf-8")
    with pytest.raises(registry.RegistryError, match="chain"):
        registry.verify(p)
    p.write_text(lines[1] + "\n", encoding="utf-8")                  # a deleted first line
    with pytest.raises(registry.RegistryError, match="chain"):
        registry.verify(p)


@pytest.mark.unit
def test_a_signal_after_the_open_is_refused_and_does_not_count(tmp_path):
    p = tmp_path / "r.jsonl"
    with pytest.raises(registry.RegistryError, match="too late"):
        _sig(p, now=IST.localize(datetime(2026, 11, 2, 9, 15)))
    assert not registry.counts(p, symbol="NIFTY", entry_date=date(2026, 11, 2), spec_hash="abc", horizon=5)
    _sig(p, now=IST.localize(datetime(2026, 11, 2, 9, 14, 59)))
    assert registry.counts(p, symbol="NIFTY", entry_date=date(2026, 11, 2), spec_hash="abc", horizon=5)


@pytest.mark.unit
def test_a_missed_day_is_recorded_and_cannot_be_backfilled(tmp_path):
    p = tmp_path / "r.jsonl"
    registry.record_missed(p, day=date(2026, 10, 30), spec_hash="abc", now=IST.localize(datetime(2026, 11, 2, 8, 0)), reason="job down")
    with pytest.raises(registry.RegistryError, match="backfilled"):
        _sig(p)
    assert registry.verify(p) == 1


@pytest.mark.unit
def test_a_duplicate_signal_is_refused(tmp_path):
    p = tmp_path / "r.jsonl"
    _sig(p)
    with pytest.raises(registry.RegistryError, match="already"):
        _sig(p)
