"""Planted bugs: the sanity checks must catch a unit error, a one-day look-ahead and a stale feature (docs/pipeline_audit_v1.md)."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.test_research_features import _build, _chain, _cut, _sessions, _world
from tradingagents.research import features as fx, sanity


def _vol_table(seed=0):
    rng = np.random.default_rng(seed)
    n = 500
    return pd.DataFrame({"symbol": "AAA", "signal_date": pd.bdate_range("2020-01-01", periods=n), "garch_h5": rng.uniform(0.2, 0.5, n), "rv_20": rng.uniform(0.2, 0.5, n), "ret_1": rng.normal(0, 0.02, n), "breadth_up_1_U1": rng.uniform(0.3, 0.7, n)})


@pytest.mark.unit
def test_clean_values_raise_nothing():
    assert sanity.check_ranges(_vol_table()) == []


@pytest.mark.unit
@pytest.mark.parametrize(("column", "factor"), [("garch_h5", 1 / 77), ("garch_h5", 100.0), ("rv_20", 100.0), ("ret_1", 100.0), ("breadth_up_1_U1", 100.0)])
def test_a_planted_unit_error_is_caught(column, factor):
    t = _vol_table()
    t[column] = t[column] * factor
    assert any(p.startswith(column) for p in sanity.check_ranges(t))


@pytest.mark.unit
def test_the_real_garch_defect_would_have_been_caught():
    """The values PR 66 produced: a median near 0.0045."""
    t = _vol_table().assign(garch_h5=lambda x: x["garch_h5"] / 77)
    assert sanity.check_ranges(t)[0].startswith("garch_h5: median")


@pytest.mark.unit
def test_a_planted_one_day_look_ahead_is_caught_on_a_real_build():
    w = _world()
    chain = _chain(w)
    day = pd.Timestamp(_sessions()[260])
    full = _build(w, chain)["a"]
    cut = _build(_cut(w, day.date()), chain[pd.to_datetime(chain["trade_date"]) < day])["a"]
    keys, cols = ["signal_date", "symbol"], ["ret_1", "rv_20"]
    clean = sanity.check_lookahead(full[full["signal_date"] == day][keys + cols], cut[cut["signal_date"] == day][keys + cols], keys, cols)
    assert clean == []
    leaked = full.sort_values(["symbol", "signal_date"]).copy()
    leaked["ret_1"] = leaked.groupby("symbol")["ret_1"].shift(-1)         # tomorrow's return
    caught = sanity.check_lookahead(leaked[leaked["signal_date"] == day][keys + cols], cut[cut["signal_date"] == day][keys + cols], keys, cols)
    assert any(p.startswith("ret_1") for p in caught)


@pytest.mark.unit
def test_a_planted_stale_feature_is_caught_and_a_clean_one_is_not():
    t = _vol_table()
    assert sanity.check_stale(t, "symbol", "signal_date", ["rv_20"]) == []
    t["rv_20"] = t["rv_20"].iloc[::5].reindex(t.index).ffill()              # carried forward across sessions
    assert sanity.check_stale(t, "symbol", "signal_date", ["rv_20"])[0].startswith("rv_20")


@pytest.mark.unit
def test_columns_that_legitimately_repeat_are_not_called_stale():
    t = _vol_table().assign(expiry_week=0.0, nifty_above_ma_50=1.0)
    assert sanity.check_stale(t, "symbol", "signal_date", ["expiry_week", "nifty_above_ma_50"]) == []


@pytest.mark.unit
def test_the_holiday_bar_class_a_row_on_no_session_never_gets_a_value():
    """PA-32's class: a bar on a day with no session. The builder keeps no row for a session with no futures row."""
    w = _world()
    days = _sessions()
    f = w["futures"]
    w = {**w, "futures": f[f["trade_date"] != days[150]], "holes": [days[150]]}
    a = _build(w)["a"]
    assert not (pd.to_datetime(a["source_trade_date"]) == pd.Timestamp(days[150])).any()


@pytest.mark.unit
def test_the_rule_table_units_class_percent_is_not_added_to_a_fraction():
    """The addendum 4 class: a schedule report in percent must become a fraction before it meets an expectancy."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(fx.g.ROOT, "scripts")))
    import research_gate2_addendum4 as a4

    out = a4.rule_offsets({"always_long": {"development": {"upper_minus_mean": 1.0}, "validation": {"upper_minus_mean": 1.0}, "window_100": {"median_upper_minus_mean": 1.0, "p90_upper_minus_mean": 1.0}}})
    assert all(v["always_long"] == 0.01 for k, v in out.items() if k != "one_schedule")


@pytest.mark.unit
def test_the_lot_loop_class_alternating_blips_settle():
    """PA-35's class: one pass of the lot despike could flip alternating blips around."""
    from tradingagents.analytics.base_store import despike_until_stable

    lots = pd.Series([100.0, 200.0, 100.0, 200.0, 100.0, 200.0, 100.0, 100.0])
    out = despike_until_stable(lots)
    assert despike_until_stable(out).equals(out)


@pytest.mark.unit
def test_the_adanient_class_an_action_subject_outside_the_kinds_is_still_a_discontinuity():
    """The ADANIENT class: a listed scheme of arrangement must blank that session's price features."""
    w = _world()
    day = _sessions()[200]
    f = w["futures"].copy()
    hit = (f["symbol"] == "S05") & (f["trade_date"] >= day)
    f.loc[hit, ["open", "high", "low", "close", "settle"]] *= 0.7
    w = {**w, "futures": f, "events": pd.DataFrame({"symbol": ["S05"], "ex_date": [day], "subject": ["Scheme Of Arrangement"]})}
    a = _build(w)["a"]
    row = a[(a["symbol"] == "S05") & (pd.to_datetime(a["source_trade_date"]) == pd.Timestamp(day))].iloc[0]
    assert np.isnan(row["ret_1"]) and date(2019, 1, 1) + timedelta(days=0) < day
