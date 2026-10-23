"""Phase 4 of the quant plan: regimes that use only the past and mean the same thing every refit."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import regime as rg


def two_regime_market(n=1100, seed=0):
    """An index alternating calm (low vol, drift up) and stress (high vol, drift down) blocks."""
    rng = np.random.default_rng(seed)
    vols, drifts = [], []
    for block in range(n // 100 + 1):
        stress = block % 3 == 2
        vols += [0.03 if stress else 0.006] * 100
        drifts += [-0.002 if stress else 0.0006] * 100
    r = rng.normal(np.array(drifts[:n]), np.array(vols[:n]))
    idx = pd.bdate_range("2018-01-01", periods=n)
    close = pd.Series(10000 * np.exp(np.cumsum(r)), index=idx)
    # VIX tracks the true vol with noise, as the real one does (a noiseless copy is degenerate).
    true_vol = np.array(vols[:n]) * np.sqrt(252) * 100
    vix = pd.Series(true_vol * np.exp(rng.normal(0, 0.08, n)), index=idx)
    return close, vix, np.array(vols[:n]) > 0.01


@pytest.mark.unit
def test_filtered_probabilities_ignore_later_data():
    close, vix, _ = two_regime_market()
    feats = rg.features(close, vix)
    full = rg.regime_probabilities(feats, min_train=500, refit_every=200)
    t = full.index[150]
    cut = rg.regime_probabilities(feats.loc[:t], min_train=500, refit_every=200)
    assert np.allclose(cut.loc[t].to_numpy(), full.loc[t].to_numpy())


@pytest.mark.unit
def test_forward_filter_differs_from_smoothed_probabilities():
    """The filter must not equal hmmlearn's forward-backward output, which peeks ahead."""
    close, vix, _ = two_regime_market()
    feats = rg.features(close, vix)
    Z = ((feats - feats.mean()) / feats.std()).to_numpy()
    model = rg._fit(Z, seed=0)
    filtered = rg.forward_filter(model, Z)
    smoothed = model.predict_proba(Z)
    assert np.allclose(filtered[-1], smoothed[-1], atol=1e-6)      # identical at the last day
    assert not np.allclose(filtered[:-50], smoothed[:-50], atol=1e-3)


@pytest.mark.unit
def test_stress_label_finds_the_high_volatility_blocks():
    close, vix, stressed = two_regime_market()
    feats = rg.features(close, vix)
    probs = rg.regime_probabilities(feats, min_train=500, refit_every=200)
    labels = rg.stable_labels(probs)
    truth = pd.Series(stressed, index=close.index).reindex(labels.index)
    hit = ((labels == "stress") == truth).mean()
    assert hit > 0.85
    table = rg.describe(labels, close)
    assert table.loc["stress", "next21_vol"] > 2 * table.loc["calm", "next21_vol"]


@pytest.mark.unit
def test_labels_need_two_confident_days_to_switch():
    probs = pd.DataFrame({"p_calm": [0.9, 0.2, 0.9, 0.2, 0.2, 0.2],
                          "p_choppy": [0.05] * 6,
                          "p_stress": [0.05, 0.75, 0.05, 0.75, 0.75, 0.75]})
    assert list(rg.stable_labels(probs)) == ["calm", "calm", "calm", "calm", "stress", "stress"]


@pytest.mark.unit
def test_breadth_is_the_share_of_stocks_above_their_50_day_average():
    idx = pd.bdate_range("2020-01-01", periods=120)
    up = pd.Series(np.linspace(100, 200, 120), index=idx)
    stocks = pd.DataFrame({"A": up, "B": up, "C": up[::-1].to_numpy(), "D": up})
    feats = rg.features(up, pd.Series(15.0, index=idx), stocks)
    assert feats["breadth"].iloc[-1] == pytest.approx(0.75)
