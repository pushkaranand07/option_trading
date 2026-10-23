"""Stress tests for a frozen strategy (PROOF_PLAN.md, Stage 2).

Pure functions over a strategy's trade results (fractions of max risk); the
scenario runs themselves live in scripts/quant_stress.py.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from tradingagents.analytics.costs import ChargeRates, Slippage


def scaled_rates(rates: ChargeRates, factor: float) -> ChargeRates:
    """Every charge multiplied by ``factor`` (GST rate unchanged: it applies to the scaled charges)."""
    def scale(d):
        return {k: (tuple(x * factor for x in v) if isinstance(v, tuple) else v * factor) for k, v in d.items()}

    return replace(rates, stt=scale(rates.stt), stt_options_exercise=rates.stt_options_exercise * factor,
                   exchange=scale(rates.exchange), sebi_fee=rates.sebi_fee * factor, stamp=scale(rates.stamp),
                   brokerage_flat=scale(rates.brokerage_flat), dp_charge=rates.dp_charge * factor)


def scaled_slippage(slip: Slippage, factor: float) -> Slippage:
    return replace(slip, equity_bps=slip.equity_bps * factor, option_ticks=int(round(slip.option_ticks * factor)),
                   option_premium_pct=slip.option_premium_pct * factor)


def block_bootstrap_ci(returns, runs: int = 10_000, block: int = 5, level: float = 0.95, seed: int = 0):
    """Confidence interval of the mean by resampling blocks of consecutive trades
    (blocks keep the clustering of losses that a plain bootstrap would break up)."""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < block * 2:
        raise ValueError("too few trades for a block bootstrap")
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n - block + 1, size=(runs, -(-n // block)))
    means = np.array([np.concatenate([r[s: s + block] for s in row])[:n].mean() for row in starts])
    lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def max_drawdown_units(returns) -> float:
    """Worst peak-to-trough fall of the running sum, in units of max risk per trade."""
    path = np.cumsum(np.asarray(returns, dtype=float))
    peak = np.maximum.accumulate(np.concatenate([[0.0], path]))[1:]
    return float((path - peak).min())


def drawdown_monte_carlo(returns, runs: int = 10_000, q: float = 0.95, seed: int = 0) -> float:
    """The ``q`` quantile of the worst drawdown over random reorderings of the trades (units of max risk)."""
    r = np.asarray(returns, dtype=float)
    rng = np.random.default_rng(seed)
    dds = np.array([max_drawdown_units(rng.permutation(r)) for _ in range(runs)])
    return float(np.quantile(dds, 1 - q))
