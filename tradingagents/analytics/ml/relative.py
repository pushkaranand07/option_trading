"""Relative strength: will this stock beat the rest of the universe? (plan, Phase 6, second model)

The first model asked "will this stock rise"; both runs leaned on market-wide
features (timing the whole market, badly) and their calibration drifted with
the 2021-26 bull run. This asks a stock-picking question instead:

- Label: entering at session *t*'s open and holding ``horizon`` sessions, did the
  stock's open-to-open return beat the equal-weight average of the universe?
  About half the stocks do on any day, whatever the market did.
- Features: each stock-level feature becomes its percentile rank across the
  universe that day; market-wide context is kept as is, so the model can learn
  interactions (e.g. "momentum leaders do better when calm").
- Trading: every ``horizon`` sessions buy the top ``k`` stocks by predicted
  probability, equal weight, and hold to the next rebalance. Judged on the
  return *in excess of holding all stocks equally* (implementable on Dhan by
  pairing the stocks with a short NIFTY future; that hedge is charged too).

``k`` and ``horizon`` are fixed before testing (one trial). Neighbouring ``k``
values are reported as a robustness check, never used to choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradingagents.analytics import evaluate as ev
from tradingagents.analytics.costs import cost_fraction
from tradingagents.analytics.gates import Evidence, GateReport, check_gates
from tradingagents.analytics.ml import model as mm
from tradingagents.analytics.ml.pipeline import mean_daily_auc
from tradingagents.analytics.validation import deflated_sharpe_ratio, evidence_verdict, sharpe


def relative_labels(opens: pd.DataFrame, horizon: int = 10) -> pd.DataFrame:
    """Per (session, symbol): open-to-open return over ``horizon`` sessions, minus the
    universe's equal-weight return over the same window; ``label`` = beat it."""
    fwd = opens.shift(-horizon) / opens - 1.0
    bench = fwd.mean(axis=1)
    rel = fwd.sub(bench, axis=0)
    t1 = pd.Series(opens.index, index=opens.index).shift(-horizon)
    out = pd.DataFrame({"ret": fwd.stack(), "rel": rel.stack()})
    out.index.names = ["date", "symbol"]
    out = out.dropna().reset_index()
    out["label"] = (out["rel"] > 0).astype(int)
    out["t1"] = out["date"].map(t1)
    return out.dropna(subset=["t1"])


def rank_features(feats: pd.DataFrame, context: list[str]) -> pd.DataFrame:
    """Stock-level columns -> percentile rank within each date; ``context`` columns unchanged."""
    stock_cols = [c for c in feats.columns if c not in set(context)]
    ranked = feats[stock_cols].groupby(level="date").rank(pct=True)
    return pd.concat([ranked, feats[[c for c in context if c in feats.columns]]], axis=1)


def portfolio(pred: pd.DataFrame, data: pd.DataFrame, k: int, horizon: int, cost: pd.Series,
              hedge_cost: float, dates: pd.DatetimeIndex, keep: int | None = None,
              swaps: list[int] | None = None, rng: np.random.Generator | None = None,
              ) -> tuple[pd.Series, pd.Series, int, list[int]]:
    """Top-``k`` long book rebalanced every ``horizon`` sessions over ``dates``.

    ``keep``: a held stock stays while it ranks within the top ``keep`` (a buffer that
    cuts turnover); only the stocks that drop out are replaced. ``None`` rebuilds the
    book from the top ``k`` every time.

    Random mode (``rng`` given): ignores the predictions and, at rebalance *i*, swaps
    ``swaps[i]`` randomly chosen holdings for random non-held stocks (all ``k`` at the
    first), so it trades exactly as often as the model did; any difference is then
    *which* stocks were held, not how much was paid in costs.

    Returns (excess daily returns net of costs, long-book daily returns, number of new
    entries, swaps per rebalance). The benchmark is all stocks equally; each rebalance
    pays the stock round trips that change and the hedge's roll.
    """
    index = data.index[(data.index >= dates[0]) & (data.index <= dates[-1])]
    sess = ev.session_returns(data.loc[index]).fillna(0.0)
    bench = sess.mean(axis=1)
    pos = pd.DataFrame(0.0, index=index, columns=data["close"].columns)
    by_date = dict(iter(pred.groupby("date")))
    rebalance = [d for d in index[::horizon] if d in by_date]
    held: list[str] = []
    made: list[int] = []
    for i, d in enumerate(rebalance):
        universe = by_date[d]["symbol"].tolist()
        if rng is not None:
            if not held:
                new_held = list(rng.choice(universe, size=min(k, len(universe)), replace=False))
            else:
                n = min(swaps[i] if swaps and i < len(swaps) else 0, k)
                stay = [s for s in held if s in universe]
                drop = set(rng.choice(stay, size=min(n, len(stay)), replace=False)) if n else set()
                kept = [s for s in stay if s not in drop]
                pool_ = [s for s in universe if s not in held]       # never re-pick a dropped stock
                add = list(rng.choice(pool_, size=min(k - len(kept), len(pool_)), replace=False))
                new_held = kept + add
        else:
            ranked = by_date[d].sort_values("p", ascending=False)["symbol"].tolist()
            kept = [s for s in held if keep and s in ranked[:keep]]
            new_held = kept + [s for s in ranked if s not in kept][: k - len(kept)]
        made.append(len(set(new_held) - set(held)))
        held = new_held
        end = rebalance[i + 1] if i + 1 < len(rebalance) else index[-1]
        span = pos.index[(pos.index >= d) & (pos.index < end)]
        pos.loc[span, :] = 0.0
        pos.loc[span, held] = 1.0 / k
    gross = (pos * sess).sum(axis=1)
    turnover = pos.diff().abs()
    turnover.iloc[0] = pos.iloc[0].abs()
    stock_costs = (turnover * (cost.reindex(pos.columns).fillna(0.0) / 2.0)).sum(axis=1)
    hedge = pd.Series(0.0, index=index)
    hedge.loc[[d for d in rebalance if d in hedge.index]] = hedge_cost      # roll the short future
    long_book = gross - stock_costs
    invested = pos.sum(axis=1) > 0
    excess = (long_book - bench.where(invested, 0.0)) - hedge
    return excess, long_book, int(sum(made)), made


@dataclass
class RelativeResult:
    predictions: pd.DataFrame
    auc: float
    daily_auc: float
    reliability: pd.DataFrame
    importance: pd.Series
    k: int
    horizon: int
    picks: int
    excess: pd.Series
    long_book: pd.Series
    excess_sharpe: float
    long_sharpe: float
    bench_sharpe: float
    deflated_sharpe: float
    verdict: str
    neighbour_sharpes: dict[int, float]
    random_percentile: float | None
    gates: GateReport
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        e = self.excess
        ann = e.mean() * 252
        lines = [
            f"Relative-strength model: top {self.k} of the universe, rebalanced every {self.horizon} sessions",
            f"Out of sample {e.index[0]:%Y-%m-%d} to {e.index[-1]:%Y-%m-%d}: {self.picks} picks",
            f"AUC {self.auc:.3f} | same-day AUC (stock picking) {self.daily_auc:.3f}",
            "Reliability (predicted vs actual):\n" + self.reliability.round(3).to_string(),
            "Top features: " + ", ".join(self.importance.head(8).index),
            f"Excess over equal-weight universe, after costs and hedge: {ann:+.1%} a year, "
            f"Sharpe {self.excess_sharpe:.2f} | DSR {self.deflated_sharpe:.2f} | verdict {self.verdict}",
            f"Long book alone: Sharpe {self.long_sharpe:.2f} vs equal-weight universe {self.bench_sharpe:.2f}",
            "Robustness (excess Sharpe at other k): " + ", ".join(f"k={k}: {v:.2f}"
                                                                for k, v in self.neighbour_sharpes.items()),
        ]
        if self.random_percentile is not None:
            lines.append(f"Beats random {self.k}-stock picks on the same schedule in {self.random_percentile:.0%} of runs")
        lines += self.notes
        lines.append(self.gates.summary())
        return "\n".join(lines)


def run(
    data: pd.DataFrame,
    feats: pd.DataFrame,
    labels: pd.DataFrame,
    context: list[str],
    position_value: float,
    k: int = 5,
    horizon: int = 10,
    keep: int | None = None,
    train: int = 756,
    test: int = 126,
    embargo: int | None = None,
    random_runs: int = 300,
    leak_mismatches: int | None = None,
    regimes: pd.Series | None = None,
    n_trials: int = 1,
    seed: int = 0,
) -> RelativeResult:
    from sklearn.metrics import roc_auc_score

    embargo = horizon + 5 if embargo is None else embargo
    X_all = rank_features(feats, context)
    lab = labels.set_index(["date", "symbol"])
    frame = X_all.join(lab, how="inner").dropna(subset=["label"])
    cols = list(X_all.columns)
    dates = frame.index.get_level_values("date").to_series(index=frame.index)
    sessions = pd.DatetimeIndex(sorted(dates.unique()))

    last_close = data["close"].ffill().iloc[-1]
    cost = pd.Series({s: cost_fraction("delivery", float(px), position_value / float(px))
                      for s, px in last_close.items() if pd.notna(px) and px > 0})
    # Hedge: a NIFTY future sized like the book, rolled every rebalance.
    hedge_cost = cost_fraction("futures", 25_000.0, max(1.0, k * position_value / 25_000.0))

    preds, importances, is_srs, notes = [], [], [], []
    for f in mm.purged_folds(sessions, train, test, embargo):
        tr_mask = dates.isin(f.train_dates) & (frame["t1"] < f.test_dates[0])
        te_mask = dates.isin(f.test_dates)
        tr, te = frame[tr_mask], frame[te_mask]
        if tr["label"].nunique() < 2 or te.empty:
            continue
        fitted = mm.fit(tr[cols], tr["label"].astype(int), dates[tr_mask], tr["t1"], seed=seed)
        notes += fitted.notes
        importances.append(fitted.importance)
        cal_dates = np.sort(dates[tr_mask].unique())
        cal = tr[dates[tr_mask] >= pd.Timestamp(cal_dates[int(len(cal_dates) * 0.85)])]
        cal_pred = cal[["label"]].assign(p=fitted.predict(cal[cols])).reset_index()
        is_srs.append(sharpe(portfolio(cal_pred, data, k, horizon, cost, hedge_cost,
                                       pd.DatetimeIndex(sorted(cal_pred["date"].unique())), keep=keep)[0]))
        out = te[["label", "rel", "t1"]].copy()
        out["p"] = fitted.predict(te[cols])
        preds.append(out)
    if not preds:
        raise ValueError("no fold could be trained")

    pred = pd.concat(preds).reset_index()
    y, p = pred["label"].to_numpy(int), pred["p"].to_numpy(float)
    oos_dates = pd.DatetimeIndex(sorted(pred["date"].unique()))
    excess, long_book, picks, swaps = portfolio(pred, data, k, horizon, cost, hedge_cost, oos_dates, keep=keep)
    oos_index = excess.index
    bench = ev.session_returns(data.loc[oos_index]).fillna(0.0).mean(axis=1)
    ex_sr = sharpe(excess)
    dsr = deflated_sharpe_ratio(excess, n_trials)
    verdict = evidence_verdict(picks, dsr)

    neighbours = {}
    for kk in (max(1, k - 2), k + 3):
        kk_keep = None if keep is None else keep - k + kk
        neighbours[kk] = sharpe(portfolio(pred, data, kk, horizon, cost, hedge_cost, oos_dates, keep=kk_keep)[0])

    random_pct = None
    if random_runs:
        rng = np.random.default_rng(seed)
        rand = []
        for _ in range(random_runs):
            # Same number of swaps at each rebalance as the model: a turnover-matched baseline.
            rand.append(sharpe(portfolio(pred, data, k, horizon, cost, hedge_cost, oos_dates,
                                         swaps=swaps, rng=rng)[0]))
        random_pct = float((np.array(rand) < ex_sr).mean())

    by_regime = {}
    if regimes is not None:
        lbl = regimes.reindex(oos_index, method="ffill")
        by_regime = excess.groupby(lbl.to_numpy()).mean().to_dict()
    folds = mm.purged_folds(sessions, train, test, embargo)
    fold_returns = [float((1 + excess.loc[f.test_dates[0]: f.test_dates[-1]]).prod() - 1)
                    for f in folds if f.test_dates[0] >= oos_index[0]]
    finite_is = [x for x in is_srs if np.isfinite(x)]
    finite_nb = [v for v in neighbours.values() if np.isfinite(v)]
    evidence = Evidence(
        oos_returns=excess, fold_returns=fold_returns, n_oos_trades=picks, deflated_sharpe=dsr,
        in_sample_sharpe=float(np.mean(finite_is)) if finite_is else None, oos_sharpe=ex_sr,
        lookahead_mismatches=leak_mismatches, regime_expectancy=by_regime or None,
        chosen_sharpe=ex_sr if finite_nb else None, neighbour_sharpes=finite_nb or None)
    rel = mm.reliability(p, y)
    importance = pd.concat(importances, axis=1).mean(axis=1).sort_values(ascending=False)
    return RelativeResult(pred, float(roc_auc_score(y, p)), mean_daily_auc(pred), rel, importance, k, horizon,
                          picks, excess, long_book, ex_sr, sharpe(long_book), sharpe(bench), dsr, verdict,
                          neighbours, random_pct, check_gates(evidence), notes)
