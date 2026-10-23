"""Phase 6, approach A: predicting move size per stock."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import evaluate as ev
from tradingagents.analytics.ml import features as mf, move_size as ms


def market(n=1300, k=15, wandering_vol=False, seed=0):
    """Stocks with constant volatility, or with volatility that wanders persistently per stock."""
    rng = np.random.default_rng(seed)
    cols = {}
    for j in range(k):
        if wandering_vol:
            logv = np.zeros(n)
            for i in range(1, n):
                logv[i] = 0.98 * logv[i - 1] + rng.normal(0, 0.12)
            vol = 0.015 * np.exp(logv)
        else:
            vol = np.full(n, 0.015)
        cols[f"S{j:02d}"] = 100 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol))
    closes = pd.DataFrame(cols, index=pd.bdate_range("2018-01-01", periods=n))
    opens = closes.shift(1).fillna(closes.iloc[0])
    long = closes.stack().rename("close").reset_index()
    long.columns = ["trade_date", "symbol", "close"]
    long["open"] = opens.stack().to_numpy()
    long["high"] = long[["open", "close"]].max(axis=1) * 1.002
    long["low"] = long[["open", "close"]].min(axis=1) * 0.998
    long["adj_close"] = long["close"]
    long["volume"] = 1e6
    long["trade_date"] = long["trade_date"].dt.date
    return ev.panel(long)


@pytest.mark.unit
def test_big_move_label_compares_the_move_with_the_expected_move():
    idx = pd.bdate_range("2026-01-01", periods=80)
    closes = pd.DataFrame({"A": 100 * np.exp(np.cumsum(np.r_[0, np.tile([0.01, -0.01], 39), 0.0]))}, index=idx)
    opens = closes.copy()
    opens.iloc[-10:] = opens.iloc[-11] * 1.30            # a +30% jump into the last window
    lab = ms.move_labels(opens, closes, horizon=10).set_index("date")
    assert lab["label"].iloc[-1] == 1                     # 30% vs ~1% daily vol x sqrt(10): big
    assert lab["label"].iloc[:-12].eq(0).all()            # the quiet stretch: no big moves
    assert (lab["expected"] > 0).all()


def _run(data):
    feats = mf.build(data, with_structure=False)
    labels = ms.move_labels(data["open"], data["close"], horizon=10)
    return ms.run(feats, labels, context=[], train=756, test=125)


@pytest.mark.unit
def test_with_constant_volatility_nothing_predicts_which_stock_moves():
    result = _run(market(wandering_vol=False, seed=1))
    assert 0.47 < result.daily_auc < 0.53


@pytest.mark.unit
def test_with_wandering_volatility_the_model_finds_the_quiet_and_busy_stocks():
    result = _run(market(wandering_vol=True, seed=2))
    # "Big" is relative to each stock's own trailing vol, which absorbs much of the wandering;
    # what is left to predict is the change in vol, so a real edge is modest but consistent.
    assert result.daily_auc > 0.55, result.summary()
    assert min(result.fold_daily_auc) > 0.53
    assert any(f in result.importance.head(4).index for f in ("vol20", "atr_pct", "vol_ratio"))
