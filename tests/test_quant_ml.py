"""Phase 6 of the quant plan: labels, features, purging and the walk-forward model."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import evaluate as ev
from tradingagents.analytics.ml import features as mf
from tradingagents.analytics.ml import labels as ml
from tradingagents.analytics.ml import model as mm
from tradingagents.analytics.ml import pipeline as mp


def panel_from(prices: pd.DataFrame) -> pd.DataFrame:
    """Each session opens at the previous close (no overnight gap), so a move that is
    predictable from yesterday's close is still ahead of a trader entering at the open."""
    opens = prices.shift(1).fillna(prices.iloc[0])
    long = prices.stack().rename("close").reset_index()
    long.columns = ["trade_date", "symbol", "close"]
    long["open"] = opens.stack().to_numpy()
    long["trade_date"] = long["trade_date"].dt.date
    long["high"] = long["close"] * 1.005
    long["low"] = long["close"] * 0.995
    long["adj_close"] = long["close"]
    long["volume"] = 1e6
    return ev.panel(long)


def ar_market(n=1600, k=20, phi=0.0, seed=0):
    rng = np.random.default_rng(seed)
    cols = {}
    for j in range(k):
        e = rng.normal(0, 0.015, n)
        r = np.zeros(n)
        for i in range(1, n):
            r[i] = phi * r[i - 1] + e[i]
        cols[f"S{j}"] = 100 * np.exp(np.cumsum(r))
    return panel_from(pd.DataFrame(cols, index=pd.bdate_range("2018-01-01", periods=n)))


@pytest.mark.unit
def test_labels_follow_the_first_barrier_crossed_at_a_close():
    idx = pd.bdate_range("2026-01-01", periods=8)
    opens = pd.DataFrame({"A": [100, 100, 101, 103, 106, 106, 106, 106.0]}, index=idx)
    closes = pd.DataFrame({"A": [100, 101, 102, 105, 106, 106, 106, 106.0]}, index=idx)
    sigma = pd.DataFrame({"A": [0.02] * 8}, index=idx)
    out = ml.triple_barrier(opens, closes, sigma, k=1.0, horizon=4).set_index("date")
    first = out.loc[idx[0]]
    # Barrier = 100 * (1 + 0.02 * 2) = 104: first crossed at the close of idx[3], exit open idx[4].
    assert (first["label"], first["exit_reason"], first["t1"]) == (1, "upper", idx[4])
    assert first["ret"] == pytest.approx(0.06)
    assert idx[4] not in out.index           # its window runs past the data: no label


@pytest.mark.unit
def test_time_limit_exits_at_the_horizon_open_and_a_flat_trade_is_not_a_win():
    idx = pd.bdate_range("2026-01-01", periods=6)
    flat = pd.DataFrame({"A": [100.0] * 6}, index=idx)
    out = ml.triple_barrier(flat, flat, pd.DataFrame({"A": [0.02] * 6}, index=idx), horizon=3)
    row = out.iloc[0]
    assert (row["label"], row["exit_reason"], row["t1"], row["sessions"]) == (0, "time", idx[3], 3)


@pytest.mark.unit
def test_a_lower_barrier_exit_with_a_gap_up_open_is_still_labelled_by_its_return():
    idx = pd.bdate_range("2026-01-01", periods=6)
    opens = pd.DataFrame({"A": [100, 100, 100, 101, 100, 100.0]}, index=idx)
    closes = pd.DataFrame({"A": [100, 95, 100, 100, 100, 100.0]}, index=idx)
    out = ml.triple_barrier(opens, closes, pd.DataFrame({"A": [0.02] * 6}, index=idx), horizon=3).iloc[0]
    # Close 95 breaks the lower barrier (~96.5); the exit is the next open, 100: flat, so not a win.
    assert (out["exit_reason"], out["label"], out["ret"]) == ("lower", 0, 0.0)


@pytest.mark.unit
def test_features_for_a_session_use_only_earlier_rows():
    data = ar_market(n=400, k=3, seed=1)
    full = mf.build(data, with_structure=True)
    rng = np.random.default_rng(0)
    for i in (260, 300, 350):
        cut = data.iloc[: i + 1].copy()
        cut.iloc[-1] = cut.iloc[-1] * rng.uniform(0.5, 1.5, cut.shape[1])     # scramble session i itself
        part = mf.build(cut, with_structure=True)
        day = data.index[i]
        a, b = full.loc[day].sort_index(), part.loc[day].sort_index()
        assert np.allclose(a.to_numpy(float), b.to_numpy(float), equal_nan=True), day


@pytest.mark.unit
def test_purge_drops_samples_whose_label_reaches_the_test_window():
    dates = pd.Series(pd.to_datetime(["2026-01-01", "2026-01-05", "2026-01-08"]))
    t1 = pd.Series(pd.to_datetime(["2026-01-04", "2026-01-12", "2026-01-09"]))
    assert list(mm.purge(dates, t1, pd.Timestamp("2026-01-10"))) == [True, False, True]


@pytest.mark.unit
def test_positions_never_overlap_within_a_stock():
    idx = pd.bdate_range("2026-01-01", periods=10)
    entries = pd.DataFrame({"date": [idx[0], idx[2], idx[5]], "symbol": "A", "t1": [idx[4], idx[6], idx[8]]})
    pos = mp.positions_from_signals(entries, idx, pd.Index(["A"]))["A"]
    assert list(pos) == [1, 1, 1, 1, 0, 1, 1, 1, 0, 0]


def _run(data, **kw):
    feats = mf.build(data, with_structure=False)
    labels = ml.triple_barrier(data["open"], data["close"], ml.causal_daily_vol(data["close"]), k=1.0, horizon=5)
    return mp.run(data, feats, labels, position_value=500_000, train=756, test=125, embargo=10,
                  random_runs=50, leak_mismatches=0, **kw)


@pytest.mark.unit
def test_on_pure_noise_the_model_finds_nothing():
    result = _run(ar_market(phi=0.0, seed=2))
    assert 0.45 < result.auc < 0.55
    assert not result.gates.approved


@pytest.mark.unit
def test_a_planted_momentum_pattern_is_found_and_calibrated():
    result = _run(ar_market(phi=0.3, seed=3))
    assert result.auc > 0.53, result.summary()
    assert result.verdict == "significant" and result.stats.expectancy > 0
    assert result.importance.index[0] in {"ret_1", "ret_5", "bb_pos", "rsi14", "dist_ma20"}
    rel = result.reliability[result.reliability["n"] >= 200]
    # Allowed miss per bucket: 3 points plus 3 standard errors of its hit rate.
    allowed = 0.03 + 3 * np.sqrt(rel["actual"] * (1 - rel["actual"]) / rel["n"])
    assert (rel["gap"].abs() < allowed).all(), rel


@pytest.mark.unit
def test_leak_check_passes_real_features_and_catches_a_peeking_one():
    data = ar_market(n=400, k=3, seed=4)
    assert mf.leak_check(data, samples=4, with_structure=False) == 0
    peek = {"next_return": lambda d: np.log(d["close"]).diff().shift(-1)}   # known only after the session
    assert mf.leak_check(data, samples=4, with_structure=False, extra=peek) > 0


@pytest.mark.unit
def test_back_to_back_trades_are_counted_separately_and_each_pays_costs():
    idx = pd.bdate_range("2026-01-01", periods=10)
    entries = pd.DataFrame({"date": [idx[0], idx[3]], "symbol": "A", "t1": [idx[3], idx[6]], "ret": [0.02, 0.01]})
    trades = mp.ledger_from_entries(entries, idx, pd.Series({"A": 0.004}))
    assert [t.net_return for t in trades] == pytest.approx([0.016, 0.006])
    assert [t.sessions for t in trades] == [3, 3]
