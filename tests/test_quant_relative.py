"""Phase 6, relative-strength model: labels, ranking, portfolio accounting and the walk-forward."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import evaluate as ev
from tradingagents.analytics.ml import features as mf, relative as mr


def market(n=1500, k=20, drift=0.0, seed=0):
    """Common market moves plus each stock's own moves. With ``drift`` > 0 each stock also
    has a slowly wandering tendency to out- or under-perform (persistence 0.98): a planted
    multi-week stock-picking signal, the kind that could survive a 0.3% round-trip cost."""
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0.0004, 0.01, n)
    cols = {}
    for j in range(k):
        mu = np.zeros(n)
        for i in range(1, n):
            mu[i] = 0.98 * mu[i - 1] + rng.normal(0, drift)
        cols[f"S{j:02d}"] = 100 * np.exp(np.cumsum(mkt + mu + rng.normal(0, 0.012, n)))
    closes = pd.DataFrame(cols, index=pd.bdate_range("2018-01-01", periods=n))
    opens = closes.shift(1).fillna(closes.iloc[0])
    long = closes.stack().rename("close").reset_index()
    long.columns = ["trade_date", "symbol", "close"]
    long["open"] = opens.stack().to_numpy()
    long["high"] = long[["open", "close"]].max(axis=1) * 1.003
    long["low"] = long[["open", "close"]].min(axis=1) * 0.997
    long["adj_close"] = long["close"]
    long["volume"] = 1e6
    long["trade_date"] = long["trade_date"].dt.date
    return ev.panel(long)


@pytest.mark.unit
def test_labels_compare_each_stock_with_the_universe_average():
    idx = pd.bdate_range("2026-01-01", periods=4)
    opens = pd.DataFrame({"A": [100, 110, 0, 0.0], "B": [100, 90, 0, 0.0]}, index=idx).replace(0, 100.0)
    lab = mr.relative_labels(opens, horizon=1).set_index(["date", "symbol"])
    assert lab.loc[(idx[0], "A"), "rel"] == pytest.approx(0.10) and lab.loc[(idx[0], "A"), "label"] == 1
    assert lab.loc[(idx[0], "B"), "rel"] == pytest.approx(-0.10) and lab.loc[(idx[0], "B"), "label"] == 0
    assert lab.loc[(idx[0], "A"), "t1"] == idx[1]
    assert idx[3] not in lab.index.get_level_values("date")          # no window left: no label


@pytest.mark.unit
def test_stock_features_become_ranks_and_context_stays():
    idx = pd.MultiIndex.from_product([pd.bdate_range("2026-01-01", periods=1), ["A", "B", "C", "D"]],
                                     names=["date", "symbol"])
    feats = pd.DataFrame({"mom": [3.0, 1.0, 2.0, 4.0], "vix": [15.0] * 4}, index=idx)
    out = mr.rank_features(feats, context=["vix"])
    assert list(out["mom"]) == [0.75, 0.25, 0.5, 1.0]
    assert list(out["vix"]) == [15.0] * 4


@pytest.mark.unit
def test_perfect_foresight_picks_beat_the_universe_and_random_picks_do_not():
    data = market(n=300, k=10, seed=1)
    labels = mr.relative_labels(data["open"], horizon=5)
    dates = pd.DatetimeIndex(sorted(labels["date"].unique()))
    cost = pd.Series(0.0, index=data["close"].columns)
    oracle = labels.assign(p=labels["rel"])
    excess, _, picks = mr.portfolio(oracle, data, 3, 5, cost, 0.0, dates)
    assert excess.mean() > 0.002 and picks > 100
    random = labels.assign(p=np.random.default_rng(0).random(len(labels)))
    rand_excess, _, _ = mr.portfolio(random, data, 3, 5, cost, 0.0, dates)
    assert abs(rand_excess.mean()) < excess.mean() / 5


def _run(data, **kw):
    feats = mf.build(data, with_structure=False)
    labels = mr.relative_labels(data["open"], horizon=10)
    return mr.run(data, feats, labels, context=[], position_value=500_000, k=3, horizon=10,
                  train=756, test=125, random_runs=50, leak_mismatches=0, **kw)


@pytest.mark.unit
def test_on_noise_there_is_no_stock_picking_edge():
    result = _run(market(drift=0.0, seed=2))
    assert 0.47 < result.daily_auc < 0.53
    assert not result.gates.approved


@pytest.mark.unit
def test_a_planted_stock_specific_pattern_is_found():
    result = _run(market(drift=0.0005, seed=3))
    assert result.daily_auc > 0.53, result.summary()
    assert result.excess_sharpe > 1.0
    assert result.random_percentile >= 0.95
