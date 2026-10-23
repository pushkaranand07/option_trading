"""Walk-forward LightGBM: out-of-sample probabilities, then a trading rule judged by the gates.

1. For each fold, train on the purged training window, predict the test window.
   Only these out-of-sample predictions are ever used below.
2. Score the predictions: AUC per fold, Brier score, reliability table.
3. Trade them: in each fold, the entry threshold is chosen from the grid on that
   fold's own calibration slice (never on test data). A long entry at session
   *t*'s open when ``p > threshold`` and no position is open in that stock; it
   exits as its label does (barrier close -> next open, or the time limit).
4. Costs, trade ledger, baselines and gates as in the Phase 2 harness; the
   grid's size is the deflated Sharpe's trial count.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradingagents.analytics import evaluate as ev
from tradingagents.analytics.costs import cost_fraction
from tradingagents.analytics.gates import Evidence, GateReport, check_gates
from tradingagents.analytics.ml import model as mm
from tradingagents.analytics.validation import deflated_sharpe_ratio, evidence_verdict, sharpe

THRESHOLDS = (0.52, 0.55, 0.58, 0.62)
MIN_SLICE_TRADES = 30


@dataclass
class MLResult:
    predictions: pd.DataFrame
    fold_auc: list[float]
    auc: float
    daily_auc: float
    brier: float
    base_rate: float
    reliability: pd.DataFrame
    importance: pd.Series
    folds: list[dict]
    trades: list[ev.Trade]
    stats: ev.TradeStats
    oos_net: pd.DataFrame
    oos_sharpe: float
    deflated_sharpe: float
    verdict: str
    baselines: dict[str, float]
    random_percentile: float | None
    gates: GateReport
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s, r = self.stats, self.oos_net.mean(axis=1)
        lines = [
            f"Predictions: {len(self.predictions):,} out-of-sample rows, base rate {self.base_rate:.1%}",
            f"AUC {self.auc:.3f} (folds {min(self.fold_auc):.3f}..{max(self.fold_auc):.3f}) | "
            f"same-day AUC (stock picking) {self.daily_auc:.3f} | Brier {self.brier:.4f}",
            "Reliability (predicted vs actual):\n" + self.reliability.round(3).to_string(),
            "Top features: " + ", ".join(f"{k}" for k in self.importance.head(8).index),
            f"Thresholds chosen per fold: {[f['threshold'] for f in self.folds]}",
            f"Trades {s.n} | hit {s.hit_rate:.1%} | payoff {s.payoff:.2f} | expectancy {s.expectancy:+.3%} "
            f"after costs",
            f"OOS Sharpe {self.oos_sharpe:.2f} | DSR {self.deflated_sharpe:.2f} | verdict {self.verdict} | "
            f"{r.index[0]:%Y-%m-%d} to {r.index[-1]:%Y-%m-%d}",
            "Baselines (OOS Sharpe): " + ", ".join(f"{k} {v:.2f}" for k, v in self.baselines.items()),
        ]
        if self.random_percentile is not None:
            lines.append(f"Beats the same trades at random dates in {self.random_percentile:.0%} of runs")
        lines += self.notes
        lines.append(self.gates.summary())
        return "\n".join(lines)


def _choose_threshold(p: np.ndarray, ret: np.ndarray, thresholds) -> float:
    """The threshold whose selected calibration-slice samples had the best mean return."""
    best, best_mean = max(thresholds), -np.inf
    for thr in thresholds:
        picked = ret[p > thr]
        if len(picked) >= MIN_SLICE_TRADES and picked.mean() > best_mean:
            best, best_mean = thr, float(picked.mean())
    return best


def _slice_sharpe(pred: pd.DataFrame, thr: float, data: pd.DataFrame, cost: pd.Series) -> float:
    """Sharpe of trading ``pred`` (date, symbol, p, t1) at ``thr`` over the dates it covers."""
    dates = pd.DatetimeIndex(sorted(pred["date"].unique()))
    index = data.index[(data.index >= dates[0]) & (data.index <= dates[-1])]
    if len(index) < 20:
        return float("nan")
    return sharpe(trading_returns(pred[pred["p"] > thr], data.loc[index], cost).mean(axis=1))


def taken_entries(entries: pd.DataFrame, index: pd.Index) -> pd.DataFrame:
    """The entries actually traded: per stock, a signal while a position is open is skipped."""
    loc = {d: i for i, d in enumerate(index)}
    kept = []
    for _, g in entries.sort_values("date").groupby("symbol"):
        busy_until = -1
        for row in g.itertuples():
            i, j = loc.get(row.date), loc.get(row.t1)
            if i is None or j is None or i < busy_until:
                continue
            kept.append(row.Index)
            busy_until = j
    return entries.loc[kept]


def positions_from_signals(entries: pd.DataFrame, index: pd.Index, columns: pd.Index) -> pd.DataFrame:
    """Long 1 from each taken entry's session up to (not including) its exit session."""
    pos = pd.DataFrame(0.0, index=index, columns=columns)
    loc = {d: i for i, d in enumerate(index)}
    for row in taken_entries(entries, index).itertuples(index=False):
        pos.iloc[loc[row.date]:loc[row.t1], pos.columns.get_loc(row.symbol)] = 1.0
    return pos


def trading_returns(entries: pd.DataFrame, data: pd.DataFrame, cost: pd.Series) -> pd.DataFrame:
    """Per-stock net daily returns of the taken entries, costed like the ledger.

    ``strategy_returns`` charges on position changes, so an exit and a re-entry on
    the same open (position stays 1) would pay nothing; a manual trader places both
    orders there, so that session pays a full round trip extra.
    """
    index = data.index
    net = ev.strategy_returns(data, positions_from_signals(entries, index, data["close"].columns), cost)
    taken = taken_entries(entries, index).sort_values(["symbol", "date"])
    joins = taken[taken["date"].to_numpy() == taken.groupby("symbol")["t1"].shift().to_numpy()]
    for row in joins.itertuples(index=False):
        net.loc[row.date, row.symbol] -= float(cost.get(row.symbol, 0.0))
    return net


def ledger_from_entries(entries: pd.DataFrame, index: pd.Index, cost: pd.Series) -> list[ev.Trade]:
    """One trade per taken entry, each paying a full round trip, even when one exit
    and the next entry fall on the same open (a manual trader places both orders)."""
    loc = {d: i for i, d in enumerate(index)}
    return [ev.Trade(r.symbol, 1.0, r.date, index[loc[r.t1] - 1], loc[r.t1] - loc[r.date],
                     float(r.ret) - float(cost.get(r.symbol, 0.0)))
            for r in taken_entries(entries, index).itertuples(index=False)]


def mean_daily_auc(pred: pd.DataFrame, min_names: int = 10) -> float:
    """Average AUC across stocks on the same day: stock picking, with market timing taken out."""
    from sklearn.metrics import roc_auc_score

    aucs = [roc_auc_score(g["label"], g["p"]) for _, g in pred.groupby("date")
            if len(g) >= min_names and g["label"].nunique() == 2]
    return float(np.mean(aucs)) if aucs else float("nan")


def run(
    data: pd.DataFrame,
    feats: pd.DataFrame,
    labels: pd.DataFrame,
    position_value: float,
    segment: str = "delivery",
    train: int = 756,
    test: int = 126,
    embargo: int = 15,
    thresholds=THRESHOLDS,
    random_runs: int = 300,
    leak_mismatches: int | None = None,
    regimes: pd.Series | None = None,
) -> MLResult:
    from sklearn.metrics import brier_score_loss, roc_auc_score

    lab = labels.set_index(["date", "symbol"])
    frame = feats.join(lab, how="inner").dropna(subset=["label"])
    feature_cols = list(feats.columns)
    frame = frame.dropna(subset=feature_cols, how="all")
    dates = frame.index.get_level_values("date").to_series(index=frame.index)
    sessions = pd.DatetimeIndex(sorted(dates.unique()))

    last_close = data["close"].ffill().iloc[-1]
    cost = pd.Series({s: cost_fraction(segment, float(px), position_value / float(px))
                      for s, px in last_close.items() if pd.notna(px) and px > 0})
    thresholds = sorted(thresholds)

    preds, folds, aucs, importances, notes = [], [], [], [], []
    is_srs, stability = [], []
    for f in mm.purged_folds(sessions, train, test, embargo):
        tr_mask = dates.isin(f.train_dates) & (frame["t1"] < f.test_dates[0])
        te_mask = dates.isin(f.test_dates)
        tr, te = frame[tr_mask], frame[te_mask]
        if tr["label"].nunique() < 2 or te.empty:
            continue
        fitted = mm.fit(tr[feature_cols], tr["label"].astype(int),
                        dates[tr_mask], tr["t1"])
        notes += fitted.notes
        # Threshold from this fold's calibration slice only.
        cal_dates = np.sort(dates[tr_mask].unique())
        cal_start = pd.Timestamp(cal_dates[int(len(cal_dates) * 0.85)])
        cal = tr[dates[tr_mask] >= cal_start]
        cal_p = fitted.predict(cal[feature_cols])
        thr = _choose_threshold(cal_p, cal["ret"].to_numpy(), thresholds)
        # In-sample view, on the calibration slice: Sharpe at the chosen threshold
        # and at its neighbours in the grid (parameter stability).
        cal_pred = cal[["t1"]].assign(p=cal_p).reset_index()
        chosen = _slice_sharpe(cal_pred, thr, data, cost)
        is_srs.append(chosen)
        i = thresholds.index(thr)
        nbrs = [_slice_sharpe(cal_pred, thresholds[j], data, cost) for j in (i - 1, i + 1)
                if 0 <= j < len(thresholds)]
        nbrs = [x for x in nbrs if np.isfinite(x)]
        if nbrs and np.isfinite(chosen) and chosen > 0:
            stability.append(float(np.median(nbrs)) / chosen)
        p = fitted.predict(te[feature_cols])
        out = te[["label", "ret", "t1"]].copy()
        out["p"] = p
        preds.append(out)
        if te["label"].nunique() == 2:
            aucs.append(float(roc_auc_score(te["label"], p)))
        importances.append(fitted.importance)
        folds.append({"test_start": f.test_dates[0], "test_end": f.test_dates[-1], "threshold": thr,
                      "trees": fitted.best_iteration})
    if not preds:
        raise ValueError("no fold could be trained: history too short or labels one-sided")

    pred = pd.concat(preds).reset_index()
    y, p = pred["label"].to_numpy(int), pred["p"].to_numpy(float)
    auc = float(roc_auc_score(y, p)) if len(set(y)) == 2 else float("nan")
    brier = float(brier_score_loss(y, p))
    rel = mm.reliability(p, y)
    importance = pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False)

    # Trading on the out-of-sample probabilities.
    thr_by_date = pd.Series(np.nan, index=pd.DatetimeIndex(pred["date"].unique()).sort_values())
    for f in folds:
        thr_by_date[(thr_by_date.index >= f["test_start"]) & (thr_by_date.index <= f["test_end"])] = f["threshold"]
    entries = pred[pred["p"].to_numpy() > pred["date"].map(thr_by_date).to_numpy()]
    oos_index = data.index[(data.index >= folds[0]["test_start"]) & (data.index <= folds[-1]["test_end"])]
    oos_data = data.loc[oos_index]
    net = trading_returns(entries, oos_data, cost)
    port = net.mean(axis=1)
    trades = ledger_from_entries(entries, oos_index, cost)
    stats = ev.TradeStats.of(trades)
    oos_sr = sharpe(port)
    dsr = deflated_sharpe_ratio(port, len(thresholds))
    verdict = evidence_verdict(stats.n, dsr)

    baselines = {"buy_and_hold": sharpe(ev.strategy_returns(
        oos_data, ev.buy_and_hold(oos_data, {}), cost).mean(axis=1))}
    random_pct = None
    if trades and random_runs:
        rand = ev.random_entry_sharpes(trades, oos_index, ev.session_returns(oos_data), cost, random_runs)
        random_pct = float((rand < oos_sr).mean())

    by_regime = {}
    if regimes is not None and trades:
        lbl = regimes.reindex(pd.DatetimeIndex([t.entry for t in trades]), method="ffill")
        fr = pd.DataFrame({"regime": lbl.to_numpy(), "r": [t.net_return for t in trades]}).dropna()
        by_regime = fr.groupby("regime")["r"].mean().to_dict()
    fold_returns = [float((1 + port.loc[f["test_start"]: f["test_end"]]).prod() - 1) for f in folds]
    finite_is = [x for x in is_srs if np.isfinite(x)]
    evidence = Evidence(oos_returns=port, fold_returns=fold_returns, n_oos_trades=stats.n, deflated_sharpe=dsr,
                        oos_sharpe=oos_sr, in_sample_sharpe=float(np.mean(finite_is)) if finite_is else None,
                        lookahead_mismatches=leak_mismatches, regime_expectancy=by_regime or None,
                        # Each fold's ratio is median(neighbours) / chosen; pass their mean against 1.
                        chosen_sharpe=1.0 if stability else None,
                        neighbour_sharpes=[float(np.mean(stability))] if stability else None)
    return MLResult(pred, aucs, auc, mean_daily_auc(pred), brier, float(y.mean()), rel, importance, folds, trades, stats, net,
                    oos_sr, dsr, verdict, baselines, random_pct, check_gates(evidence), notes)
