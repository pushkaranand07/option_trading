"""Volatility risk premium signal and its walk-forward test on iron condors (plan, Phase 3).

``VRP = 30-day ATM implied vol - GARCH forecast of the next 21 sessions``, both
known after day *d*'s close. A condor may be entered on session *t* when the
VRP's z-score over the previous year, as of *t-1*, is above ``z``.

The question the walk-forward answers is not "do condors make money" but "does
entering only when VRP is high beat entering whenever possible, and beat
entering on random days?" Both baselines use the same condor rules.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from tradingagents.analytics import condor as cd
from tradingagents.analytics.gates import Evidence, GateReport, check_gates
from tradingagents.analytics.validation import (
    deflated_sharpe_ratio,
    evidence_verdict,
    sharpe,
    walk_forward_splits,
)

Z_WINDOW = 252


def vrp_series(iv30: pd.Series, garch_h21: pd.Series) -> pd.Series:
    """IV minus forecast, on the dates both exist (dated by the close they are known after)."""
    both = pd.concat({"iv": iv30, "f": garch_h21}, axis=1).dropna()
    return both["iv"] - both["f"]


def vrp_signal(vrp: pd.Series, z: float, sessions: pd.Index, window: int = Z_WINDOW) -> pd.Series:
    """True on session *t* when the z-score known at the previous close exceeds ``z``."""
    mean = vrp.rolling(window, min_periods=window // 2).mean()
    sd = vrp.rolling(window, min_periods=window // 2).std()
    zscore = ((vrp - mean) / sd).reindex(sessions).ffill()
    return (zscore.shift(1) > z).fillna(False)


@dataclass
class CondorEvaluation:
    name: str
    folds: list[dict]
    oos_daily: pd.Series
    oos_trades: list[cd.CondorTrade]
    oos_sharpe: float
    in_sample_sharpe: float
    deflated_sharpe: float
    verdict: str
    baselines: dict[str, float]
    random_percentile: float | None
    gates: GateReport

    def summary(self) -> str:
        s = cd.summarize(self.oos_trades)
        r = self.oos_daily
        lines = [f"== {self.name} ==",
                 f"Out-of-sample {r.index[0]:%Y-%m-%d} to {r.index[-1]:%Y-%m-%d}, {len(self.folds)} folds; "
                 f"params chosen per fold: {[f['params'] for f in self.folds]}"]
        if s["trades"]:
            lines.append(f"Trades {s['trades']} | hit {s['hit_rate']:.1%} | avg return on risk "
                         f"{s['avg_return_on_risk']:+.2%} | worst {s['worst_return_on_risk']:+.1%} | "
                         f"exits {s['exit_reasons']} | flagged {s['flagged']}")
        lines.append(f"Sharpe IS {self.in_sample_sharpe:.2f} -> OOS {self.oos_sharpe:.2f} | "
                     f"DSR {self.deflated_sharpe:.2f} | verdict {self.verdict}")
        lines.append("Baselines (OOS Sharpe, same condor rules): "
                     + ", ".join(f"{k} {v:.2f}" for k, v in self.baselines.items()))
        if self.random_percentile is not None:
            lines.append(f"Beats random entry days in {self.random_percentile:.0%} of runs (needs >= 95%)")
        lines.append(self.gates.summary())
        return "\n".join(lines)


def evaluate_condor(
    name: str,
    chain: pd.DataFrame,
    spot: pd.Series,
    lots: pd.Series,
    vrp: pd.Series,
    grid: list[dict],
    train: int = 756,
    test: int = 126,
    embargo: int = 45,
    random_runs: int = 100,
    seed: int = 0,
    regimes: pd.Series | None = None,
    regimes_switched_off: frozenset[str] = frozenset(),
    **sim_kwargs,
) -> CondorEvaluation:
    """Walk-forward over ``grid`` (keys: ``z`` plus any ``CondorParams`` field).

    Each grid point is simulated over the whole history once; each fold picks
    the point with the best training Sharpe and keeps its test-window days and
    the trades entered in them. The embargo (default 45 sessions) exceeds the
    longest condor, so no training trade is still open in the test window.

    ``regimes``: the regime label known at the start of each session (the
    label dated the previous close). Each out-of-sample trade is tagged with
    the label on its entry day, which feeds the regime gate.
    """
    sessions = pd.to_datetime(pd.Index(sorted(set(pd.to_datetime(chain["trade_date"])))))
    runs = {}
    for i, g in enumerate(grid):
        params = replace(cd.CondorParams(), **{k: v for k, v in g.items() if k != "z"})
        signal = vrp_signal(vrp, g["z"], sessions)
        runs[i] = cd.simulate(chain, spot, lots, signal, params, **sim_kwargs)

    folds, oos_trades, is_srs, trial_srs = [], [], [], []
    for split in walk_forward_splits(sessions, train, test, embargo=embargo):
        scored = []
        for i, (_, daily) in runs.items():
            tr = daily.reindex(split.train).fillna(0.0)
            scored.append((sharpe(tr), i))
            trial_srs.append(sharpe(tr, 1))
        best_sr, best = max(scored)
        trades, _ = runs[best]
        lo, hi = split.test[0].date(), split.test[-1].date()
        oos_trades += [t for t in trades if lo <= t.entry_date <= hi]
        is_srs.append(best_sr)
        folds.append({"params": grid[best], "train_sharpe": best_sr, "test_start": split.test[0],
                      "test_end": split.test[-1]})
    if not folds:
        raise ValueError("history too short for one walk-forward split")
    # The out-of-sample series is exactly the out-of-sample trades' daily P&L, over their
    # whole lives (a trade entered near a fold's end runs into the next window), so trade
    # statistics, Sharpe and the gates all describe the same trades.
    first = folds[0]["test_start"]
    last = max([folds[-1]["test_end"]] + [pd.Timestamp(t.exit_date) for t in oos_trades if t.exit_date])
    oos = pd.Series(0.0, index=sessions[(sessions >= first) & (sessions <= last)])
    for t in oos_trades:
        for d, v in t.daily.items():
            oos.loc[d] += v
    oos_sr = sharpe(oos)
    dsr = deflated_sharpe_ratio(oos, len(grid), trial_sharpes=trial_srs)
    verdict = evidence_verdict(len(oos_trades), dsr)

    # Baselines on the same out-of-sample days, same condor rules.
    base_params = replace(cd.CondorParams(), **{k: v for k, v in folds[-1]["params"].items() if k != "z"})
    always = pd.Series(True, index=sessions)
    _, always_daily = cd.simulate(chain, spot, lots, always, base_params, **sim_kwargs)
    baselines = {"enter_whenever_possible": sharpe(always_daily.reindex(oos.index).fillna(0.0))}
    random_pct = None
    if random_runs:
        rng = np.random.default_rng(seed)
        # The real signal's entry rate in each fold's test window, where it is used. Over
        # all sessions it would include the early years where the z-score cannot exist yet
        # (forced off), and the random strategy would fire too rarely to compare.
        on_share = float(np.mean([vrp_signal(vrp, f["params"]["z"], sessions)
                                  .loc[f["test_start"]: f["test_end"]].mean() for f in folds]))
        rand = []
        for _ in range(random_runs):
            sig = pd.Series(rng.random(len(sessions)) < on_share, index=sessions)
            _, d = cd.simulate(chain, spot, lots, sig, base_params, **sim_kwargs)
            rand.append(sharpe(d.reindex(oos.index).fillna(0.0)))
        random_pct = float((np.array(rand) < oos_sr).mean())
        baselines["random_days_median"] = float(np.median(rand))

    fold_returns = [float(oos.loc[f["test_start"]: f["test_end"]].sum()) for f in folds]
    by_regime = regime_expectancy(oos_trades, regimes) if regimes is not None else {}
    evidence = Evidence(oos_returns=oos, fold_returns=fold_returns, n_oos_trades=len(oos_trades),
                        deflated_sharpe=dsr, in_sample_sharpe=float(np.mean(is_srs)), oos_sharpe=oos_sr,
                        lookahead_mismatches=_signal_lookahead(vrp, sessions, folds[-1]["params"]["z"]),
                        regime_expectancy=by_regime or None, regimes_switched_off=regimes_switched_off)
    return CondorEvaluation(name, folds, oos, oos_trades, oos_sr, float(np.mean(is_srs)), dsr, verdict,
                            baselines, random_pct, check_gates(evidence))


def regime_expectancy(trades: list[cd.CondorTrade], regimes: pd.Series) -> dict[str, float]:
    """Mean return on risk of the trades entered in each regime."""
    labels = regimes.copy()
    labels.index = pd.to_datetime(labels.index)
    rows = [(labels.asof(pd.Timestamp(t.entry_date)), t.return_on_risk) for t in trades]
    frame = pd.DataFrame(rows, columns=["regime", "r"]).dropna()
    return frame.groupby("regime")["r"].mean().to_dict() if len(frame) else {}


def _signal_lookahead(vrp: pd.Series, sessions: pd.Index, z: float, samples: int = 40) -> int:
    """Sessions whose signal changes when VRP data from that session onward is removed."""
    full = vrp_signal(vrp, z, sessions)
    picks = sessions[len(sessions) // 3:: max(1, len(sessions) // samples)]
    bad = 0
    for t in picks:
        cut = vrp[vrp.index < t]
        if bool(vrp_signal(cut, z, sessions[sessions <= t]).iloc[-1]) != bool(full.loc[t]):
            bad += 1
    return bad
