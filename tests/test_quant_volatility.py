"""Phase 3 of the quant plan: volatility forecasts use only the past and are scored fairly."""

import math

import numpy as np
import pandas as pd
import pytest

from tradingagents.analytics import volatility_model as vm


def simulated_garch(n=1200, omega=0.05, alpha=0.10, beta=0.85, seed=0, with_variance=False):
    """Percent returns from a known GARCH(1,1); optionally also each day's true variance."""
    rng = np.random.default_rng(seed)
    var, r, v = omega / (1 - alpha - beta), np.empty(n), np.empty(n)
    for i in range(n):
        v[i] = var
        r[i] = math.sqrt(var) * rng.standard_normal()
        var = omega + alpha * r[i] ** 2 + beta * var
    idx = pd.bdate_range("2018-01-01", periods=n)
    returns = pd.Series(r, index=idx)
    return (returns, pd.Series(v, index=idx)) if with_variance else returns


@pytest.mark.unit
def test_realised_vol_looks_only_forward_from_the_next_session():
    r = pd.Series([1.0, 2.0, 3.0, 4.0], index=pd.bdate_range("2026-01-01", periods=4))
    rv = vm.realised_vol(r, horizons=(2,))["h2"]
    assert rv.iloc[0] == pytest.approx(math.sqrt((4 + 9) * 252 / 2) / 100)
    assert rv.iloc[2:].isna().all()


@pytest.mark.unit
def test_qlike_is_zero_for_a_perfect_forecast_and_punishes_underforecasting_more():
    rv = pd.Series([0.2])
    assert vm.qlike(rv, pd.Series([0.2])).iloc[0] == pytest.approx(0.0)
    assert vm.qlike(rv, pd.Series([0.1])).iloc[0] > vm.qlike(rv, pd.Series([0.4])).iloc[0]


@pytest.mark.unit
@pytest.mark.parametrize("model", ["garch", "gjr"])
def test_garch_forecast_at_t_is_unchanged_by_later_data(model):
    r = simulated_garch(n=500)
    full = vm.garch_forecasts(r, model, horizons=(5,), min_train=300, refit_every=50)
    t = r.index[420]
    cut = vm.garch_forecasts(r.loc[:t], model, horizons=(5,), min_train=300, refit_every=50)
    assert cut.loc[t, "h5"] == pytest.approx(full.loc[t, "h5"], rel=1e-9)


@pytest.mark.unit
def test_baselines_are_causal():
    r = simulated_garch(n=300)
    t = r.index[200]
    for fn in (vm.hist_vol_forecasts, vm.ewma_forecasts):
        assert fn(r.loc[:t]).loc[t, "h5"] == pytest.approx(fn(r).loc[t, "h5"])


@pytest.mark.unit
def test_garch_tracks_true_volatility_better_than_a_rolling_window():
    r, true_var = simulated_garch(n=1500, alpha=0.10, beta=0.88, omega=0.02, seed=1, with_variance=True)
    true_next = np.sqrt(true_var.shift(-1) * 252) / 100     # the vol of t+1, known in the model at t
    garch = vm.garch_forecasts(r, "garch", horizons=(1, 5), min_train=800, refit_every=350)
    hist = vm.hist_vol_forecasts(r, horizons=(1, 5))
    frame = pd.concat({"true": true_next, "garch": garch["h1"], "hist": hist["h1"]}, axis=1).dropna()
    assert frame["garch"].corr(frame["true"]) > 0.98
    assert vm.qlike(frame["true"], frame["garch"]).mean() < 0.5 * vm.qlike(frame["true"], frame["hist"]).mean()
    # Against noisy realised vol, it should still come out ahead.
    table = vm.compare({"garch": garch[["h5"]], "hist": hist[["h5"]]},
                       vm.realised_vol(r, horizons=(5,))).set_index("model")
    assert table.loc["garch", "qlike"] < table.loc["hist", "qlike"]
