"""Phase 7: Chronos volatility forecasts — timing, variance arithmetic, causal calibration."""

import numpy as np
import pandas as pd
import pytest

torch = pytest.importorskip("torch")

from tradingagents.analytics import chronos_vol as cv, volatility_model as vm  # noqa: E402


class FakePipe:
    """Quantiles from the last context value only: q10 = -x, q50 = 0, q90 = +x, where
    x is the last return seen. Records every context it was given."""

    def __init__(self):
        self.contexts = []

    def predict_quantiles(self, inputs, prediction_length, quantile_levels):
        self.contexts += [c.numpy().copy() for c in inputs]
        last = torch.stack([c[-1].abs() for c in inputs])
        q = torch.stack([-last, torch.zeros_like(last), last], dim=-1)          # (n, 3)
        q = q[:, None, :].repeat(1, prediction_length, 1)
        return q, q[:, :, 1]


def returns(n=60, seed=0):
    idx = pd.bdate_range("2020-01-01", periods=n)
    return pd.Series(np.random.default_rng(seed).normal(0, 1, n), index=idx)


@pytest.mark.unit
def test_each_forecast_sees_only_returns_up_to_its_date():
    r = returns()
    pipe = FakePipe()
    f = cv.chronos_forecasts(r, pipe, horizons=(5,), min_train=20, context=8, batch=7)
    assert f.index[0] == r.index[19] and f.index[-1] == r.index[-1] and len(f) == len(r) - 19
    for k, ctx in zip(range(19, len(r)), pipe.contexts, strict=True):
        np.testing.assert_allclose(ctx, r.to_numpy(np.float32)[k - 7: k + 1])


@pytest.mark.unit
def test_quantile_width_becomes_annualised_vol():
    r = returns()
    f = cv.chronos_forecasts(r, FakePipe(), horizons=(5, 10), min_train=20, context=8)
    x = abs(r.iloc[19])
    sigma = 2 * x / cv.INTERDECILE                                     # the same every step
    assert f["h5"].iloc[0] == pytest.approx(np.sqrt(sigma ** 2 * 252) / 100)
    assert f["h10"].iloc[0] == pytest.approx(f["h5"].iloc[0])


@pytest.mark.unit
def test_calibration_fixes_a_constant_bias_without_seeing_the_future():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 1.5, 1500), index=pd.bdate_range("2018-01-01", periods=1500))
    realised = vm.realised_vol(r, horizons=(10,))
    true_vol = pd.DataFrame({"h10": np.sqrt(1.5 ** 2 * 252) / 100}, index=r.index)
    half = true_vol / 2                                                # forecasts too low by 2x
    cal = cv.calibrate(half, realised, min_obs=252)
    assert cal.index[0] == r.index[252 + 10 - 1]                       # 252 closed windows needed
    assert cal["h10"].iloc[-200:].mean() == pytest.approx(true_vol["h10"].iloc[0], rel=0.05)
    # Changing the future does not change past calibrated forecasts.
    shocked = r.copy()
    shocked.iloc[1000:] *= 5
    cal2 = cv.calibrate(half, vm.realised_vol(shocked, horizons=(10,)), min_obs=252)
    pd.testing.assert_series_equal(cal["h10"].loc[: r.index[999]], cal2["h10"].loc[: r.index[999]])
    assert not np.allclose(cal["h10"].iloc[-1], cal2["h10"].iloc[-1])
