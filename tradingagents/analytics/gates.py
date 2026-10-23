"""Success gates every signal must pass before anything downstream may use it.

The thresholds are fixed before results are seen (docs/QUANT_SIGNAL_LAYER_PLAN.md,
Phase 0), so a disappointing backtest cannot move the goalposts. A gate whose
evidence was not supplied is ``not_evaluated``, and that is not a pass: a
strategy is ``approved`` only when every gate was checked and passed.

Build the evidence with :func:`evidence_from_walk_forward`, add what the walk
forward cannot know (look-ahead check, regime breakdown, neighbouring
parameters), then call :func:`check_gates`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from tradingagents.analytics.validation import WalkForwardResult

PASS, FAIL, NOT_EVALUATED = "pass", "fail", "not_evaluated"


@dataclass(frozen=True)
class Gates:
    min_oos_trades: int = 100
    min_deflated_sharpe: float = 0.95
    min_oos_is_sharpe_ratio: float = 0.5        # below: the in-sample result is mostly fit
    min_positive_fold_share: float = 0.7        # folds with positive return after costs
    max_drawdown_to_annual_return: float = 2.0  # |max drawdown| <= 2x average yearly return
    min_positive_regimes: int = 2               # of the regimes the strategy trades in
    min_neighbour_sharpe_ratio: float = 0.5     # median neighbour Sharpe / chosen Sharpe


@dataclass
class Evidence:
    """What is known about one strategy, all of it out-of-sample and after costs."""

    oos_returns: pd.Series | None = None
    fold_returns: list[float] | None = None     # total return of each walk-forward test window
    n_oos_trades: int | None = None
    deflated_sharpe: float | None = None
    in_sample_sharpe: float | None = None
    oos_sharpe: float | None = None
    lookahead_mismatches: int | None = None     # len(find_lookahead(...)); 0 = causal
    regime_expectancy: Mapping[str, float] | None = None  # mean trade return per regime
    regimes_switched_off: frozenset[str] = frozenset()
    chosen_sharpe: float | None = None          # Sharpe of the chosen parameters
    neighbour_sharpes: list[float] | None = None  # Sharpes of the adjacent grid points


@dataclass(frozen=True)
class GateResult:
    name: str
    status: str
    value: float | None
    threshold: str
    detail: str = ""


@dataclass
class GateReport:
    results: list[GateResult] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return bool(self.results) and all(r.status == PASS for r in self.results)

    @property
    def verdict(self) -> str:
        if self.approved:
            return "approved"
        if any(r.status == FAIL for r in self.results):
            return "rejected"
        return "incomplete"

    def summary(self) -> str:
        lines = [f"Gate verdict: {self.verdict}"]
        for r in self.results:
            value = "-" if r.value is None else f"{r.value:.3f}"
            lines.append(f"  [{r.status:>13}] {r.name}: {value} (needs {r.threshold})"
                         + (f" - {r.detail}" if r.detail else ""))
        return "\n".join(lines)


def max_drawdown(returns: pd.Series) -> float:
    """Largest peak-to-trough fall of the compounded equity curve, as a negative fraction."""
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def annual_return(returns: pd.Series, periods: int = 252) -> float:
    r = returns.fillna(0.0)
    if len(r) == 0:
        return 0.0
    growth = float((1.0 + r).prod())
    if growth <= 0:
        return -1.0
    return growth ** (periods / len(r)) - 1.0


def evidence_from_walk_forward(result: WalkForwardResult) -> Evidence:
    """Fill what a walk-forward run already knows; the caller adds the rest."""
    fold_returns = [
        float((1.0 + result.oos_returns.loc[f.test_start: f.test_end]).prod() - 1.0)
        for f in result.folds
    ]
    return Evidence(
        oos_returns=result.oos_returns,
        fold_returns=fold_returns,
        n_oos_trades=result.n_trades,
        deflated_sharpe=result.deflated_sharpe,
        in_sample_sharpe=result.in_sample_sharpe,
        oos_sharpe=result.oos_sharpe,
    )


def _result(name: str, passed: bool | None, value: float | None, threshold: str, detail: str = "") -> GateResult:
    status = NOT_EVALUATED if passed is None else (PASS if passed else FAIL)
    return GateResult(name, status, value, threshold, detail)


def _median(values: Iterable[float]) -> float:
    return float(np.median(np.asarray(list(values), dtype=float)))


def check_gates(ev: Evidence, gates: Gates = Gates(), periods: int = 252) -> GateReport:
    report = GateReport()
    add = report.results.append

    if ev.lookahead_mismatches is None:
        add(_result("no look-ahead", None, None, "0 mismatches", "run find_lookahead on the signal"))
    else:
        add(_result("no look-ahead", ev.lookahead_mismatches == 0, float(ev.lookahead_mismatches),
                    "0 mismatches"))

    if ev.n_oos_trades is None:
        add(_result("out-of-sample trades", None, None, f">= {gates.min_oos_trades}"))
    else:
        add(_result("out-of-sample trades", ev.n_oos_trades >= gates.min_oos_trades,
                    float(ev.n_oos_trades), f">= {gates.min_oos_trades}"))

    if ev.deflated_sharpe is None:
        add(_result("deflated Sharpe", None, None, f">= {gates.min_deflated_sharpe}"))
    else:
        add(_result("deflated Sharpe", ev.deflated_sharpe >= gates.min_deflated_sharpe,
                    ev.deflated_sharpe, f">= {gates.min_deflated_sharpe}"))

    if ev.in_sample_sharpe is None or ev.oos_sharpe is None:
        add(_result("OOS / IS Sharpe", None, None, f">= {gates.min_oos_is_sharpe_ratio}"))
    elif ev.in_sample_sharpe <= 0:
        add(_result("OOS / IS Sharpe", False, None, f">= {gates.min_oos_is_sharpe_ratio}",
                    "in-sample Sharpe is not positive"))
    else:
        ratio = ev.oos_sharpe / ev.in_sample_sharpe
        add(_result("OOS / IS Sharpe", ratio >= gates.min_oos_is_sharpe_ratio, ratio,
                    f">= {gates.min_oos_is_sharpe_ratio}"))

    if not ev.fold_returns:
        add(_result("positive folds", None, None, f">= {gates.min_positive_fold_share:.0%}"))
    else:
        share = sum(r > 0 for r in ev.fold_returns) / len(ev.fold_returns)
        add(_result("positive folds", share >= gates.min_positive_fold_share, share,
                    f">= {gates.min_positive_fold_share:.0%}", f"{len(ev.fold_returns)} folds"))

    if ev.oos_returns is None or len(ev.oos_returns) == 0:
        add(_result("drawdown vs return", None, None, f"<= {gates.max_drawdown_to_annual_return}x"))
    else:
        dd, yearly = abs(max_drawdown(ev.oos_returns)), annual_return(ev.oos_returns, periods)
        if yearly <= 0:
            add(_result("drawdown vs return", False, None, f"<= {gates.max_drawdown_to_annual_return}x",
                        f"annual return {yearly:.1%} is not positive"))
        else:
            ratio = dd / yearly
            add(_result("drawdown vs return", ratio <= gates.max_drawdown_to_annual_return, ratio,
                        f"<= {gates.max_drawdown_to_annual_return}x",
                        f"max DD {dd:.1%}, annual {yearly:.1%}"))

    if not ev.regime_expectancy:
        add(_result("regime stability", None, None, f">= {gates.min_positive_regimes} positive regimes"))
    else:
        # Plan, Phase 0: positive in at least N regimes, or explicitly switched off
        # in every regime where it loses.
        positive = sum(v > 0 for v in ev.regime_expectancy.values())
        traded = [v for k, v in ev.regime_expectancy.items() if k not in ev.regimes_switched_off]
        switched_off_losers = bool(traded) and all(v > 0 for v in traded)
        add(_result("regime stability", positive >= gates.min_positive_regimes or switched_off_losers,
                    float(positive),
                    f">= {gates.min_positive_regimes} positive regimes, or off where it loses",
                    ", ".join(f"{k}: {v:+.4f}" for k, v in ev.regime_expectancy.items())))

    if ev.chosen_sharpe is None or not ev.neighbour_sharpes:
        add(_result("parameter stability", None, None, f">= {gates.min_neighbour_sharpe_ratio}"))
    elif ev.chosen_sharpe <= 0 or math.isnan(ev.chosen_sharpe):
        add(_result("parameter stability", False, None, f">= {gates.min_neighbour_sharpe_ratio}",
                    "chosen Sharpe is not positive"))
    else:
        ratio = _median(ev.neighbour_sharpes) / ev.chosen_sharpe
        add(_result("parameter stability", ratio >= gates.min_neighbour_sharpe_ratio, ratio,
                    f">= {gates.min_neighbour_sharpe_ratio}",
                    f"{len(ev.neighbour_sharpes)} neighbours"))

    return report
