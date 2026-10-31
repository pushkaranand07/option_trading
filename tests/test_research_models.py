"""Model suite v1: folds, leakage, a planted signal, acting rules, gate items (docs/models_v1.json, docs/PA_47)."""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tradingagents.research import gate as g, gate2 as g2, models as m


def _sessions(start=date(2010, 1, 1), n=3400):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _rows(n=4000, seed=0, signal=False):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 3))
    gross = rng.normal(0, 0.02, n)
    if signal:
        gross = np.abs(gross) * np.sign(x[:, 0])
    return pd.DataFrame({"f1": x[:, 0], "f2": x[:, 1], "f3": x[:, 2]}), gross


@pytest.mark.unit
def test_the_spec_is_frozen_before_any_fit_and_has_at_most_6_specs(tmp_path):
    spec = m.read_spec()
    assert spec["written_before_any_fit"] and len({k[0] for k in spec["specs"]}) == 6
    assert spec["gate"]["addendum_6_sha256"] == g2.ADDENDUM_6_SHA256 and spec["trials"]["total"] == 70
    assert spec["feature_count"] == 112 and not set(spec["features"]) & set(spec["excluded_features"])
    weights = spec["specs"]["e_ensemble"]["weights"]
    assert len(set(weights.values())) == 1 and sum(weights.values()) == pytest.approx(1)
    p = tmp_path / "s.json"
    p.write_text(m.SPEC_FILE.read_text(encoding="utf-8").replace('"version": 1', '"version": 2'), encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        m.read_spec(p)


@pytest.mark.unit
def test_addendum_6_lets_item_e_fail_only_on_validation_and_forward():
    a = g2.read_addendum_6()["item_e_application"]
    assert a["can_fail_the_gate_on"] == ["validation", "forward"]


@pytest.mark.unit
def test_training_uses_earlier_folds_and_purges_h_before_the_test_fold():
    s = _sessions()
    pos = np.arange(len(s))
    h = 5
    keep = m.fit_mask(pos, pos + h, 2, h, s)      # test fold 2017-18
    start = next(i for i, d in enumerate(s) if d.year >= 2017)
    assert keep[(pos + h) < start - h].sum() > 0
    assert not keep[pos + h >= start - h].any()     # nothing ends within the purge
    y = np.array([d.year for d in s])
    assert keep[y == 2013].mean() > 0.9              # an earlier test fold stays as history
    end13 = next(i for i, d in enumerate(s) if d.year >= 2015)
    assert not keep[end13:end13 + h].any()           # the embargo after that fold


@pytest.mark.unit
def test_the_frozen_train_mask_really_drops_earlier_folds_which_is_why_it_is_not_used():
    s = _sessions()
    entry, exit_ = pd.Series(s[:-5]), pd.Series(s[5:])
    keep = g.train_mask(entry, exit_, 2, 5, s)
    y = np.array([d.year for d in s[:-5]])
    assert keep[y == 2013].sum() == 0


@pytest.mark.unit
def test_the_inner_holdout_comes_last_and_is_purged():
    pos = np.repeat(np.arange(100), 3)
    fit, hold = m.inner_split(pos, pos + 2, 2)
    assert pos[hold].min() == 80 and (pos[fit] + 2).max() < 80 - 2


@pytest.mark.unit
def test_winsor_limits_and_scaling_come_only_from_training_rows():
    x, _ = _rows(1000)
    train, test = x.iloc[:800], x.iloc[800:].copy()
    a = m.Prep(train, ["f1", "f2"], {"g": ["f1", "f2"]})
    test.loc[test.index[0], "f1"] = 1e9
    b = m.Prep(train, ["f1", "f2"], {"g": ["f1", "f2"]})
    assert (a.mean == m.Prep(x.iloc[:800], ["f1", "f2"], {"g": ["f1", "f2"]}).mean).all()
    assert a.limits["f1"][1] < 10                     # the outlier in the test rows did not reach the limits
    assert b.matrix(test)[0, 0] == pytest.approx((a.limits["f1"][1] - a.mean[0]) / a.std[0])


@pytest.mark.unit
def test_missing_gets_a_flag_and_zero_and_is_not_filled_from_other_rows():
    x, _ = _rows(100)
    x.loc[5, "f1"] = np.nan
    p = m.Prep(x, ["f1", "f2"], {"g": ["f1"]})
    out = p.matrix(x)
    assert out[5, 0] == 0.0 and out[5, 2] == 1.0 and out[6, 2] == 0.0


@pytest.mark.unit
@pytest.mark.parametrize("fit", [m.fit_sgd_logistic, m.fit_lgbm_classifier], ids=["elastic", "lightgbm"])
def test_a_planted_signal_is_found_and_a_shuffled_one_is_not(fit):
    x, gross = _rows(6000, signal=True)
    params = {"alpha": 0.0001, "l1_ratio": 0.15, "max_depth": 3}
    p = m.Prep(x.iloc[:4000], ["f1", "f2", "f3"], {})
    y = gross[:4000] > 0
    good = fit(x.iloc[:4000], y, p, params, 0)(x.iloc[4000:])
    assert ((good > 0.5) == (gross[4000:] > 0)).mean() > 0.9
    hits = []          # one shuffle can land on a lucky coefficient; the average cannot
    for s in range(9):
        bad = fit(x.iloc[:4000], np.random.default_rng(s).permutation(y), p, params, s)(x.iloc[4000:])
        hits.append(((bad > 0.5) == (gross[4000:] > 0)).mean())
    assert abs(np.mean(hits) - 0.5) < 0.12


def _panel(n_days=60, syms=8, seed=0):
    rng = np.random.default_rng(seed)
    rows = [{"signal_pos": d, "sym": s, "f1": rng.normal(), "f2": rng.normal()} for d in range(n_days) for s in range(syms)]
    f = pd.DataFrame(rows)
    return f, m.sequence_index(f["sym"].to_numpy(), f["signal_pos"].to_numpy())


@pytest.mark.unit
def test_a_sequence_only_looks_back_and_a_gap_stays_empty():
    f, seq = _panel()
    row = f.index[(f["sym"] == 2) & (f["signal_pos"] == 30)][0]
    assert list(f.loc[seq[row], "signal_pos"]) == list(range(21, 31)) and set(f.loc[seq[row], "sym"]) == {2}
    gap = f[~((f["sym"] == 2) & (f["signal_pos"] == 28))].reset_index(drop=True)
    s2 = m.sequence_index(gap["sym"].to_numpy(), gap["signal_pos"].to_numpy())
    r2 = gap.index[(gap["sym"] == 2) & (gap["signal_pos"] == 30)][0]
    assert s2[r2, 7] == -1 and (s2[gap.index[gap["signal_pos"] == 3], 0] == -1).all()


@pytest.mark.unit
def test_a_sequence_prediction_for_d_does_not_change_with_later_rows():
    f, seq = _panel()
    f = f.assign(panel_row=np.arange(len(f)))
    y = (f["f1"].to_numpy() > 0)
    train = f[f["signal_pos"] < 40]
    p = m.Prep(train, ["f1", "f2"], {"g": ["f1", "f2"]})
    day = f[f["signal_pos"] == 45]
    full = m.fit_tcn(train, y[train.index], p, {"channels": 4}, 0, panel={"frame": f, "seq": seq}, threads=1)(day)
    later = f.copy()
    later.loc[later["signal_pos"] > 45, ["f1", "f2"]] = 99.0
    other = m.fit_tcn(train, y[train.index], p, {"channels": 4}, 0, panel={"frame": later, "seq": seq}, threads=1)(day)
    assert full == pytest.approx(other, abs=1e-6)


@pytest.mark.unit
def test_acting_rules():
    assert list(m.act_probability(np.array([0.6, 0.5, 0.4, 0.52]), 0.03)) == [1, 0, -1, 0]
    assert list(m.act_magnitude(np.array([0.01, -0.01, 0.001]), np.array([0.002] * 3), 2)) == [1, -1, 0]
    day = pd.DataFrame({"signal": ["d"] * 40})
    d = m.act_rank(day, np.arange(40.0), 0.1, np.ones(40, bool))
    assert d[-4:].tolist() == [1] * 4 and d[:4].tolist() == [-1] * 4 and d[4:-4].sum() == 0
    assert (m.act_rank(day.iloc[:19], np.arange(19.0), 0.1, np.ones(19, bool)) == 0).all()      # too few names


@pytest.mark.unit
def test_calibration_with_one_class_changes_nothing():
    x = np.array([0.2, 0.8])
    assert list(m.platt(np.array([0.3, 0.6]), np.array([1, 1]))(x)) == [0.2, 0.8]


@pytest.mark.unit
def test_the_band_is_the_median_of_each_folds_best_and_thin_settings_do_not_count():
    a = {0.01: {"net": 0.1, "dates": 60}, 0.05: {"net": 0.9, "dates": 10}}
    b = {0.01: {"net": 0.1, "dates": 60}, 0.03: {"net": 0.2, "dates": 60}}
    c = {0.03: {"net": 0.2, "dates": 60}}
    assert m.best_setting([a, b, c]) == 0.03
    assert m.best_setting([{0.01: {"net": 1, "dates": 1}}]) is None


def _u1(net_by_fold, per_fold=150):
    rows = []
    for f, mean in enumerate(net_by_fold):
        for i in range(per_fold):
            rows.append({"fold": f, "signal": f"{f}-{i}", "net": mean + (0.001 if i % 2 else -0.001), "win_null": 0.45})
    return pd.DataFrame(rows)


@pytest.mark.unit
def test_development_pass_needs_a_d_f_g_and_item_e_is_report_only_there():
    u = _u1([0.002] * 5)
    rng = np.random.default_rng(0)
    low = {"always_long": [10.0] * 20}
    r = m.development_items(u, 0.001, 3, 0.0034, 2, rng, baselines=low)
    assert r["pass"] and not r["e"]["pass"]         # loses to the baseline, still passes development
    v = m.development_items(u, 0.001, 3, 0.0034, 2, np.random.default_rng(0), baselines=low, baseline_can_fail=True)
    assert not v["pass"]                            # item e can fail on validation
    assert not m.development_items(u, -0.001, 3, 0.0034, 2, np.random.default_rng(0))["f"]["pass"]


@pytest.mark.unit
def test_item_g_fails_with_too_few_positive_folds_or_a_bad_fold_or_thin_fold():
    rng = np.random.default_rng(0)
    assert not m.development_items(_u1([0.002, 0.002, 0.002, -0.001, -0.001]), 0.001, 3, 0.01, 2, rng)["g"]["pass"]
    assert m.development_items(_u1([0.002, 0.002, 0.002, 0.002, -0.001]), 0.001, 3, 0.01, 2, rng)["g"]["pass"]
    assert not m.development_items(_u1([0.002, 0.002, 0.002, 0.002, -0.02]), 0.001, 3, 0.01, 2, rng)["g"]["pass"]
    assert not m.development_items(_u1([0.002] * 5, per_fold=99), 0.001, 3, 0.01, 2, rng)["g"]["pass"]


@pytest.mark.unit
def test_the_win_rate_is_report_only():
    r = m.development_items(_u1([0.002] * 5), 0.001, 3, 0.01, 2, np.random.default_rng(0))
    assert "win_rate" in r["b_report"] and "p" in r["c_report"] and r["pass"]


@pytest.mark.unit
def test_models_use_no_llm_and_reach_the_store_only_through_the_loader():
    text = Path(m.__file__).read_text(encoding="utf-8")
    for word in ("openai", "anthropic", "datastore", "store_root", "lot_size"):
        assert word not in text, word


def _driver():
    import sys
    sys.path.insert(0, str(Path(g.ROOT, "scripts")))
    import research_models as rm
    return rm


def _toy_rows():
    return pd.DataFrame({"symbol": ["A"] * 4 + ["B"] * 4, "signal_pos": [1, 2, 3, 4] * 2, "panel_row": range(8), "gross": [0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 0.7, -0.8],
                         "signal": [1, 2, 3, 4] * 2, "in_U1": [True] * 4 + [False] * 4, "kind": ["stock"] * 8})


@pytest.mark.unit
def test_rank_labels_use_only_u1_stocks():
    rm = _driver()
    y = rm.labels("f_rank", _toy_rows())
    assert np.isnan(y[4:]).all() and (y[:4] == 1.0).all()


@pytest.mark.unit
def test_controls_change_what_the_model_learns_or_sees_and_keep_rows_aligned():
    rm = _driver()
    r = _toy_rows()
    panel = r[["symbol", "signal_pos", "panel_row"]]
    same, y = rm.apply_control(r, panel, "time_shift", 1)
    assert same is r and y[0] == r["gross"][2] and y[3] == 0.0                # the label from 2h sessions later
    same, y = rm.apply_control(r, panel, "shuffled", 1)
    assert same is r and sorted(y) == sorted(r["gross"])
    stale, y = rm.apply_control(r, panel, "stale", 1)
    assert y is None and list(stale["panel_row"][stale["symbol"] == "A"]) == [0, 1, 2]     # features of one session earlier
    assert list(stale["signal_pos"][stale["symbol"] == "A"]) == [2, 3, 4]
    assert list(stale["gross"][stale["symbol"] == "A"]) == [-0.2, 0.3, -0.4]              # scored on real returns


@pytest.mark.unit
def test_rows_take_their_own_panel_features():
    rm = _driver()
    panel = pd.DataFrame({"panel_row": range(5), "f": [10.0, 11.0, 12.0, 13.0, 14.0]})
    rows = pd.DataFrame({"panel_row": [3, 0], "gross": [0.1, 0.2]})
    assert list(rm.frames(rows, panel, ["f"])["f"]) == [13.0, 10.0]
