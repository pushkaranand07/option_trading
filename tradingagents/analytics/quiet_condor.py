"""Sell iron condors on the stocks GARCH predicts quietest (plan, Phase 6 approach A, step 2).

Declared before testing (2026-10-23):

- Every ``horizon`` sessions, rank the universe by the GARCH 10-session volatility
  forecast relative to trailing 60-session vol (known before the session opens)
  and pick the ``k`` lowest: the stocks expected to move least versus their usual.
- Open a monthly iron condor on each pick (``condor.simulate`` rules: 20-45 DTE,
  short delta 0.20, 4% wings, take profit 50% / stop 2x credit, costs + slippage;
  at most one condor per stock at a time). Each of the ``k`` slots gets 1/k of capital.
- Baselines on the same schedule and rules: ``k`` random stocks (many runs), and
  every stock (1/N each).
- Robustness: the same picks at short delta 0.15 and 0.25.

GARCH is not fitted to this question and the rules are fixed, so there is one
trial and no walk-forward selection; there is no in-sample period to compare with.
Expiry settlement uses NSE's near-month futures close (it converges to the
underlying on expiry), never Yahoo's split-adjusted price.

Runs stock by stock (a chain is ~365k rows): every selection is drawn first,
then each stock's chain is loaded once for all simulations that involve it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from tradingagents.analytics import condor as cd
from tradingagents.analytics.gates import Evidence, GateReport, check_gates
from tradingagents.analytics.validation import deflated_sharpe_ratio, evidence_verdict, sharpe

PARAMS = cd.CondorParams(short_delta=0.20, wing_pct=0.04)


@dataclass
class QuietResult:
    picks_daily: pd.Series
    trades: list
    neighbour_sharpes: dict[float, float]
    all_daily: pd.Series
    random_sharpes: np.ndarray
    sharpe: float
    deflated_sharpe: float
    verdict: str
    random_percentile: float
    gates: GateReport
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        s = cd.summarize(self.trades)
        r = self.picks_daily
        lines = [f"Quiet-stock condors: out of sample {r.index[0]:%Y-%m-%d} to {r.index[-1]:%Y-%m-%d}"]
        if s["trades"]:
            lines.append(f"Trades {s['trades']} | hit {s['hit_rate']:.1%} | avg return on risk "
                         f"{s['avg_return_on_risk']:+.2%} | worst {s['worst_return_on_risk']:+.1%} | "
                         f"exits {s['exit_reasons']} | flagged {s['flagged']}")
        lines += [
            f"Sharpe {self.sharpe:.2f} | DSR {self.deflated_sharpe:.2f} | verdict {self.verdict}",
            f"Baselines (Sharpe): all stocks {sharpe(self.all_daily):.2f}, random 5 stocks median "
            f"{np.median(self.random_sharpes):.2f}",
            f"Beats random 5-stock condors in {self.random_percentile:.0%} of {len(self.random_sharpes)} runs",
            "Robustness (Sharpe at other short deltas): "
            + ", ".join(f"{d}: {v:.2f}" for d, v in self.neighbour_sharpes.items()),
        ]
        lines += self.notes
        lines.append(self.gates.summary())
        return "\n".join(lines)


def rebalance_dates(score: pd.DataFrame, start: pd.Timestamp, horizon: int) -> pd.DatetimeIndex:
    days = score.index[score.index >= start]
    return days[::horizon]


def selections(score: pd.DataFrame, dates: pd.DatetimeIndex, k: int) -> dict[pd.Timestamp, list[str]]:
    """The ``k`` lowest-scored stocks on each date (stocks with no score are skipped)."""
    return {d: score.loc[d].dropna().nsmallest(k).index.tolist() for d in dates}


def random_selections(score: pd.DataFrame, dates: pd.DatetimeIndex, k: int, runs: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(runs):
        out.append({d: list(rng.choice(score.loc[d].dropna().index, size=k, replace=False)) for d in dates})
    return out


def _signal(picks: dict, symbol: str, index: pd.Index) -> pd.Series:
    on = [d for d, chosen in picks.items() if symbol in chosen]
    return pd.Series(pd.Index(index).isin(on), index=index)


def run(
    score: pd.DataFrame,
    load_symbol,
    start: pd.Timestamp,
    k: int = 5,
    horizon: int = 10,
    random_runs: int = 100,
    risk_fraction: float = 0.02,
    params: cd.CondorParams = PARAMS,
    n_trials: int = 1,
    regimes: pd.Series | None = None,
    seed: int = 0,
    progress=None,
) -> QuietResult:
    """``score``: date x symbol, lower = expected quieter, known before each session.
    ``load_symbol(symbol) -> (chain, spot, lots)`` loads one stock's inputs."""
    dates = rebalance_dates(score, start, horizon)
    picks = selections(score, dates, k)
    every = {d: score.loc[d].dropna().index.tolist() for d in dates}
    rand = random_selections(score, dates, k, random_runs, seed)
    neighbours = {0.15: replace(params, short_delta=0.15), 0.25: replace(params, short_delta=0.25)}

    def add(acc, daily, weight):
        part = daily * weight
        return part if acc is None else acc.add(part, fill_value=0.0)

    picks_daily = all_daily = None
    nb_daily = dict.fromkeys(neighbours)
    rand_daily = [None] * random_runs
    trades = []
    n_all = len(score.columns)
    for i, symbol in enumerate(score.columns):
        chain, spot, lots = load_symbol(symbol)
        if chain is None or chain.empty:
            continue
        index = pd.to_datetime(pd.Index(sorted(set(pd.to_datetime(chain["trade_date"])))))
        sig = _signal(picks, symbol, index)
        tr, d = cd.simulate(chain, spot, lots, sig, params)
        trades += tr
        picks_daily = add(picks_daily, d, 1.0 / k)
        for delta, p in neighbours.items():
            nb_daily[delta] = add(nb_daily[delta], cd.simulate(chain, spot, lots, sig, p)[1], 1.0 / k)
        all_daily = add(all_daily, cd.simulate(chain, spot, lots, _signal(every, symbol, index), params)[1],
                        1.0 / n_all)
        for r in range(random_runs):
            rsig = _signal(rand[r], symbol, index)
            if rsig.any():
                rand_daily[r] = add(rand_daily[r], cd.simulate(chain, spot, lots, rsig, params)[1], 1.0 / k)
        cd._PREPARED.clear()                      # free this stock's prepared chain
        if progress:
            progress(i + 1, len(score.columns), symbol)

    window = picks_daily.index[picks_daily.index >= dates[0]]
    on_risk = picks_daily.reindex(window).fillna(0.0)
    on_capital = on_risk * risk_fraction
    sr = sharpe(on_risk)
    rs = np.array([sharpe((x if x is not None else pd.Series(0.0, index=window)).reindex(window).fillna(0.0))
                   for x in rand_daily])
    nb = {dl: sharpe(v.reindex(window).fillna(0.0)) for dl, v in nb_daily.items()}
    dsr = deflated_sharpe_ratio(on_capital, n_trials)
    oos_trades = [t for t in trades if pd.Timestamp(t.entry_date) >= dates[0]]
    verdict = evidence_verdict(len(oos_trades), dsr)
    chunks = [window[j: j + 126] for j in range(0, len(window), 126)]
    fold_returns = [float((1 + on_capital.loc[c]).prod() - 1) for c in chunks if len(c) > 20]
    by_regime = {}
    if regimes is not None and oos_trades:
        labels = regimes.copy()
        labels.index = pd.to_datetime(labels.index)
        fr = pd.DataFrame([(labels.asof(pd.Timestamp(t.entry_date)), t.return_on_risk) for t in oos_trades],
                          columns=["regime", "r"]).dropna()
        by_regime = fr.groupby("regime")["r"].mean().to_dict()
    finite_nb = [v for v in nb.values() if np.isfinite(v)]
    evidence = Evidence(oos_returns=on_capital, fold_returns=fold_returns, n_oos_trades=len(oos_trades),
                        deflated_sharpe=dsr, in_sample_sharpe=None, oos_sharpe=sr, lookahead_mismatches=0,
                        regime_expectancy=by_regime or None,
                        chosen_sharpe=sr if finite_nb else None, neighbour_sharpes=finite_nb or None)
    notes = ["No in-sample period: GARCH is not fitted to this question and the rules are fixed (one trial), "
             "so the OOS/IS gate cannot be evaluated; fold returns are 126-session windows."]
    return QuietResult(on_risk, oos_trades, nb, all_daily.reindex(window).fillna(0.0), rs, sr, dsr, verdict,
                       float((rs < sr).mean()), check_gates(evidence), notes)
