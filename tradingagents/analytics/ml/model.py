"""Purged walk-forward splits and a small, calibrated LightGBM classifier (plan, Phase 6).

Purging: a training sample's label depends on prices up to its ``t1``. If
``t1`` reaches the test window, the sample has seen test prices and is dropped
from training. The same rule separates the inner slices of a training window.

Each training window is cut in time order into:
``fit`` (model trees) | ``stop`` (early stopping) | ``calib`` (calibration),
each later slice purged of earlier slices' overlap. Calibration is therefore
fitted on predictions the trees never trained or stopped on.

Calibration is Platt scaling (a logistic fit on the model's log-odds): two
parameters, so it stays sensible on a calibration slice of a few thousand
rows, where isotonic regression overfits the rare high-probability cases.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradingagents.analytics.validation import walk_forward_splits

LGBM_PARAMS = {
    "num_leaves": 15, "min_child_samples": 200, "learning_rate": 0.03, "n_estimators": 2000,
    "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "reg_lambda": 5.0, "verbose": -1,
}


@dataclass
class Fold:
    train_dates: pd.DatetimeIndex
    test_dates: pd.DatetimeIndex


def purged_folds(sessions: pd.DatetimeIndex, train: int, test: int, embargo: int) -> list[Fold]:
    return [Fold(pd.DatetimeIndex(s.train), pd.DatetimeIndex(s.test))
            for s in walk_forward_splits(sessions, train, test, embargo=embargo)]


def purge(dates: pd.Series, t1: pd.Series, before: pd.Timestamp) -> np.ndarray:
    """Mask of samples whose whole label lies before ``before``."""
    return (dates < before).to_numpy() & (t1 < before).to_numpy()


class PlattCalibrator:
    """Logistic regression on the logit of the raw probability."""

    def fit(self, raw: np.ndarray, y: np.ndarray) -> PlattCalibrator:
        from sklearn.linear_model import LogisticRegression

        self._lr = LogisticRegression(C=1e6).fit(self._logit(raw), y)
        return self

    def predict(self, raw: np.ndarray) -> np.ndarray:
        return self._lr.predict_proba(self._logit(raw))[:, 1]

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)


@dataclass
class FittedModel:
    model: object
    calibrator: object
    best_iteration: int
    importance: pd.Series
    calib_brier_raw: float
    calib_brier: float
    notes: list[str] = field(default_factory=list)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.model.predict_proba(X, num_iteration=self.best_iteration)[:, 1]
        return self.calibrator.predict(raw)


def fit(X: pd.DataFrame, y: pd.Series, dates: pd.Series, t1: pd.Series,
        stop_frac: float = 0.15, calib_frac: float = 0.15, seed: int = 0) -> FittedModel:
    """Fit on one training window (rows already purged against the test window)."""
    from lightgbm import LGBMClassifier, early_stopping
    from sklearn.metrics import brier_score_loss

    uniq = np.sort(dates.unique())
    n = len(uniq)
    stop_start = pd.Timestamp(uniq[int(n * (1 - stop_frac - calib_frac))])
    calib_start = pd.Timestamp(uniq[int(n * (1 - calib_frac))])
    fit_mask = purge(dates, t1, stop_start)
    stop_mask = purge(dates, t1, calib_start) & (dates >= stop_start).to_numpy()
    calib_mask = (dates >= calib_start).to_numpy()
    notes = []
    if fit_mask.sum() < 500 or stop_mask.sum() < 100 or calib_mask.sum() < 100:
        notes.append(f"small slices: fit {fit_mask.sum()}, stop {stop_mask.sum()}, calib {calib_mask.sum()}")

    model = LGBMClassifier(random_state=seed, **LGBM_PARAMS)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(X[fit_mask], y[fit_mask], eval_set=[(X[stop_mask], y[stop_mask])],
                  eval_metric="binary_logloss", callbacks=[early_stopping(100, verbose=False)])
    best = int(model.best_iteration_ or LGBM_PARAMS["n_estimators"])
    raw = model.predict_proba(X[calib_mask], num_iteration=best)[:, 1]
    calibrator = PlattCalibrator().fit(raw, y[calib_mask].to_numpy())
    importance = pd.Series(model.booster_.feature_importance("gain"), index=X.columns).sort_values(ascending=False)
    return FittedModel(model, calibrator, best, importance,
                       float(brier_score_loss(y[calib_mask], raw)),
                       float(brier_score_loss(y[calib_mask], calibrator.predict(raw))), notes)


def reliability(p: np.ndarray, y: np.ndarray, edges=(0, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 1.0)) -> pd.DataFrame:
    """Predicted vs actual hit rate per probability bucket."""
    bucket = pd.cut(p, edges, include_lowest=True)
    frame = pd.DataFrame({"bucket": bucket, "p": p, "y": y})
    out = frame.groupby("bucket", observed=True).agg(n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
    out["gap"] = out["actual"] - out["predicted"]
    return out
