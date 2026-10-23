"""Predict the *size* of a stock's next move, not its direction (plan, Phase 6, approach A).

Direction proved unpredictable from public end-of-day data; volatility did not
(GARCH beat historical vol on 31/31 symbols). This asks a volatility question
per stock, declared before testing (2026-10-23):

- Label: over the next ``horizon`` sessions (entry at session *t*'s open, open to
  open), did the stock move by more than ``k_sigma`` times its expected move?
  The expected move is the trailing 60-session daily volatility (closes up to
  *t-1*) x sqrt(horizon). About a third of cases are "big" at k = 1.
- Step 1 (this module): purged walk-forward probabilities, scored by AUC and,
  above all, same-day AUC: can it tell which stocks will move big *on the
  same day*? If not, there is nothing to trade.
- Step 2 (only if step 1 passes): sell defined-risk premium on the stocks
  predicted quietest.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from tradingagents.analytics.ml import model as mm
from tradingagents.analytics.ml.pipeline import mean_daily_auc
from tradingagents.analytics.ml.relative import rank_features

VOL_WINDOW = 60


def move_labels(opens: pd.DataFrame, closes: pd.DataFrame, horizon: int = 10, k_sigma: float = 1.0) -> pd.DataFrame:
    """Per (session, symbol): ``label`` = |open-to-open move over ``horizon``| > k x expected move."""
    sigma = np.log(closes).diff().rolling(VOL_WINDOW, min_periods=VOL_WINDOW // 2).std().shift(1)
    expected = sigma * np.sqrt(horizon)
    move = opens.shift(-horizon) / opens - 1.0
    out = pd.DataFrame({"move": move.stack(), "expected": expected.reindex_like(move).stack()})
    out.index.names = ["date", "symbol"]
    out = out.dropna().reset_index()
    out["label"] = (out["move"].abs() > k_sigma * out["expected"]).astype(int)
    t1 = pd.Series(opens.index, index=opens.index).shift(-horizon)
    out["t1"] = out["date"].map(t1)
    return out.dropna(subset=["t1"])


@dataclass
class MoveResult:
    predictions: pd.DataFrame
    base_rate: float
    auc: float
    daily_auc: float
    fold_daily_auc: list[float]
    reliability: pd.DataFrame
    importance: pd.Series
    garch_daily_auc: float | None

    def summary(self) -> str:
        lines = [
            f"Move-size model: {len(self.predictions):,} out-of-sample predictions, base rate {self.base_rate:.1%}",
            f"AUC {self.auc:.3f} | same-day AUC (which stocks move big) {self.daily_auc:.3f} "
            f"(folds {min(self.fold_daily_auc):.3f}..{max(self.fold_daily_auc):.3f})",
        ]
        if self.garch_daily_auc is not None:
            lines.append(f"Benchmark: ranking by the GARCH forecast alone gives same-day AUC {self.garch_daily_auc:.3f}")
        lines += ["Reliability (predicted vs actual):\n" + self.reliability.round(3).to_string(),
                  "Top features: " + ", ".join(self.importance.head(10).index)]
        return "\n".join(lines)


def run(feats: pd.DataFrame, labels: pd.DataFrame, context: list[str], train: int = 756, test: int = 126,
        embargo: int = 15, seed: int = 0, benchmark: pd.DataFrame | None = None) -> MoveResult:
    """Purged walk-forward probabilities of a big move. ``benchmark``: an optional wide
    (date x symbol) score, e.g. the GARCH forecast as a ratio to trailing vol, scored the
    same way so the model has to beat the simple alternative."""
    from sklearn.metrics import roc_auc_score

    X_all = rank_features(feats, context)
    frame = X_all.join(labels.set_index(["date", "symbol"]), how="inner").dropna(subset=["label"])
    cols = list(X_all.columns)
    dates = frame.index.get_level_values("date").to_series(index=frame.index)
    sessions = pd.DatetimeIndex(sorted(dates.unique()))
    preds, importances, fold_aucs = [], [], []
    for f in mm.purged_folds(sessions, train, test, embargo):
        tr_mask = dates.isin(f.train_dates) & (frame["t1"] < f.test_dates[0])
        te_mask = dates.isin(f.test_dates)
        tr, te = frame[tr_mask], frame[te_mask]
        if tr["label"].nunique() < 2 or te.empty:
            continue
        fitted = mm.fit(tr[cols], tr["label"].astype(int), dates[tr_mask], tr["t1"], seed=seed)
        importances.append(fitted.importance)
        out = te[["label", "move", "t1"]].copy()
        out["p"] = fitted.predict(te[cols])
        preds.append(out)
        fold_aucs.append(mean_daily_auc(out.reset_index()))
    if not preds:
        raise ValueError("no fold could be trained")
    pred = pd.concat(preds).reset_index()
    y, p = pred["label"].to_numpy(int), pred["p"].to_numpy(float)
    garch_auc = None
    if benchmark is not None:
        b = benchmark.stack().rename("p").reset_index()
        b.columns = ["date", "symbol", "p"]
        bench = pred[["date", "symbol", "label"]].merge(b, on=["date", "symbol"], how="inner")
        garch_auc = mean_daily_auc(bench) if len(bench) else None
    return MoveResult(pred, float(y.mean()), float(roc_auc_score(y, p)), mean_daily_auc(pred),
                      [a for a in fold_aucs if np.isfinite(a)], mm.reliability(p, y),
                      pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False), garch_auc)
