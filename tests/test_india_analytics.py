"""No look-ahead in patterns (P-17) and overfitting-resistant validation (P-18)."""

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics.swings import (
    confirmed_swings,
    double_top_breakdown,
    find_lookahead,
    market_structure,
)
from tradingagents.analytics.validation import (
    deflated_sharpe_ratio,
    evidence_verdict,
    expected_max_sharpe,
    probabilistic_sharpe_ratio,
    walk_forward,
    walk_forward_splits,
)


def frame(closes):
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c})


def double_top_series():
    up = list(np.linspace(100, 120, 10))
    down = list(np.linspace(119, 108, 8))
    up2 = list(np.linspace(109, 120.5, 8))
    crash = list(np.linspace(119, 95, 12))
    return frame(up + down + up2 + crash)


@pytest.mark.unit
def test_a_swing_is_confirmed_only_after_the_right_hand_bars():
    df = double_top_series()
    highs = [s for s in confirmed_swings(df, 3, 3) if s.kind == "high"]
    assert highs, "expected swing highs"
    pos = {t: i for i, t in enumerate(df.index)}
    assert all(pos[s.confirmed_at] - pos[s.pivot_at] == 3 for s in highs)


@pytest.mark.unit
def test_double_top_fires_once_at_the_neckline_break_and_not_before():
    df = double_top_series()
    signal = double_top_breakdown(df, tolerance=0.02, min_separation=8)
    fired = list(signal[signal].index)
    assert len(fired) == 1
    neckline = df["Low"].iloc[9:18].min()
    assert df.loc[fired[0], "Close"] < neckline


@pytest.mark.unit
def test_causal_detectors_pass_the_replay_check():
    df = double_top_series()
    assert find_lookahead(lambda d: double_top_breakdown(d, tolerance=0.02, min_separation=8), df, start=5) == []
    assert find_lookahead(market_structure, df, start=5) == []


@pytest.mark.unit
def test_replay_check_catches_a_repainting_centered_pivot():
    df = double_top_series()

    def naive_pivot_high(d):    # the common mistake: a centred window stamped on the pivot bar
        return d["High"] == d["High"].rolling(7, center=True).max()

    assert find_lookahead(naive_pivot_high, df, start=5) != []


# --------------------------------------------------------------- validation


@pytest.mark.unit
def test_walk_forward_splits_never_overlap_and_respect_the_embargo():
    idx = pd.RangeIndex(100)
    splits = walk_forward_splits(idx, train=40, test=20, embargo=5)
    assert len(splits) == 2
    for s in splits:
        assert s.train[-1] + 5 < s.test[0]
        assert not set(s.train) & set(s.test)


@pytest.mark.unit
def test_expected_max_sharpe_grows_with_the_number_of_trials():
    assert expected_max_sharpe(10, 0.01) < expected_max_sharpe(1000, 0.01)
    assert expected_max_sharpe(1, 0.01) == 0.0


@pytest.mark.unit
def test_psr_and_dsr_separate_skill_from_luck():
    rng = np.random.default_rng(7)
    skilled = rng.normal(0.002, 0.01, 1000)       # per-period Sharpe ~0.2
    assert probabilistic_sharpe_ratio(skilled) > 0.99
    # The same returns judged as the best of 1,000 noisy trials need more to pass.
    assert deflated_sharpe_ratio(skilled, 1000, sr_variance=0.05 ** 2) < probabilistic_sharpe_ratio(skilled)
    noise = rng.normal(0, 0.01, 1000)
    assert deflated_sharpe_ratio(noise, 1000, sr_variance=0.05 ** 2) < 0.5


def momentum_strategy(data, params):
    """Causal: position from yesterday's lookback return, earned on today's return."""
    ret = data["Close"].pct_change().fillna(0)
    signal = np.sign(data["Close"].pct_change(params["lookback"])).shift(1).fillna(0)
    return signal * ret


GRID = [{"lookback": n} for n in (5, 10, 20, 40, 60)]


@pytest.mark.unit
def test_walk_forward_does_not_find_an_edge_in_noise():
    rng = np.random.default_rng(11)
    data = pd.DataFrame({"Close": 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1500)))},
                        index=pd.bdate_range("2018-01-01", periods=1500))
    result = walk_forward(data, momentum_strategy, GRID, train=500, test=250)
    assert result.verdict != "significant"
    assert len(result.folds) == 4
    assert result.oos_returns.index.min() == data.index[500]       # nothing in-sample leaks into OOS


@pytest.mark.unit
def test_walk_forward_finds_a_real_trend_edge():
    rng = np.random.default_rng(3)
    drift = np.where((np.arange(1500) // 250) % 2 == 0, 0.003, -0.003)   # persistent regimes
    data = pd.DataFrame({"Close": 100 * np.exp(np.cumsum(drift + rng.normal(0, 0.006, 1500)))},
                        index=pd.bdate_range("2018-01-01", periods=1500))
    result = walk_forward(data, momentum_strategy, GRID, train=500, test=250,
                          count_trades=lambda r: 200)
    assert result.oos_sharpe > 1 and result.verdict == "significant"
    assert "walk-forward" in result.summary()


@pytest.mark.unit
def test_too_few_trades_is_insufficient_evidence_whatever_the_sharpe():
    assert evidence_verdict(n_trades=12, dsr=0.999) == "insufficient_evidence"
    assert evidence_verdict(n_trades=50, dsr=0.6) == "not_significant"
