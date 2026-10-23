"""Stage 2 stress tests for the frozen pooled VRP condor (PROOF_PLAN.md).

    python scripts/quant_stress.py

Runs the frozen rules (paper_strategies.VRP_POOLED_PARAMS) over all history under
each scenario and prints a pass/fail table. Trade results are fractions of each
condor's max risk; capital figures assume Stage 4 sizing.

Crash proxy: the frozen rules' first trade is in Sept 2021 (GARCH needs 3 years of
training, the VRP z-score another year), so they have never seen a crash. For this
stress test only, GARCH is re-run with 1 year of training so the signal exists
from mid-2019, and the 2020 crash is replayed. Never used for evaluation.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import (  # noqa: E402
    condor as cd,
    datastore as ds,
    stress as st,
    volatility_model as vm,
    vrp as vp,
)
from tradingagents.analytics.costs import DEFAULT_RATES, DEFAULT_SLIPPAGE  # noqa: E402
from tradingagents.analytics.paper_strategies import VRP_POOLED_PARAMS  # noqa: E402
from tradingagents.analytics.prices import load_prices  # noqa: E402

EVENTS = {
    "COVID crash (20-Feb to 30-Apr 2020)": ("2020-02-20", "2020-04-30"),
    "Adani / Hindenburg (24-Jan to 28-Feb 2023)": ("2023-01-24", "2023-02-28"),
    "Election results (3 to 7 Jun 2024)": ("2024-06-03", "2024-06-07"),
}
MAX_OPEN_RISK = 0.03          # Stage 4: total open risk cap
MAX_CONCURRENT = 8            # 2 indices x 4 books, at most one condor each
RISK_PER_CONDOR = MAX_OPEN_RISK / MAX_CONCURRENT     # so all 8 at once stay inside the cap


def run(inputs, rates=DEFAULT_RATES, slippage=DEFAULT_SLIPPAGE, start_after_months=0, start=None) -> list:
    """The frozen rules' closed trades. ``start_after_months`` delays the first allowed entry
    (from the first date the signal fires), which changes every later position."""
    trades = []
    for symbol, p in VRP_POOLED_PARAMS.items():
        chain, spot, lots, vrp = inputs[symbol]
        sessions = pd.to_datetime(pd.Index(sorted(set(pd.to_datetime(chain["trade_date"])))))
        signal = vp.vrp_signal(vrp, p["z"], sessions)
        if start_after_months and signal.any():
            first = signal[signal].index.min()
            signal &= signal.index >= first + pd.DateOffset(months=start_after_months)
        if start is not None:
            signal &= signal.index >= pd.Timestamp(start)
        params = replace(cd.CondorParams(), short_delta=p["short_delta"], wing_pct=p["wing_pct"])
        book, _ = cd.simulate_staggered(chain, spot, lots, signal, params, books=4, rates=rates, slippage=slippage)
        for t in book:
            t.symbol = symbol
        trades += book
    return sorted((t for t in trades if t.exit_date), key=lambda t: (t.exit_date, t.entry_date))


def crash_inputs(symbol: str, min_train: int = 252):
    """Stress-only inputs reaching back to mid-2019 (GARCH trained on 1 year, not 3)."""
    chain, spot, lots, _ = vp.load_inputs(symbol)
    px = load_prices([symbol])
    close = pd.Series(px["close"].to_numpy(), index=pd.to_datetime(px["trade_date"])).sort_index()
    garch = vm.garch_forecasts(vm.log_returns(close), "garch", horizons=(21,), min_train=min_train)["h21"]
    ivt = pd.read_parquet(ds.store_root() / "iv" / "iv30.parquet").query("symbol == @symbol")
    iv30 = pd.Series(ivt["iv30"].to_numpy(), index=pd.to_datetime(ivt["trade_date"]))
    return chain, spot, lots, vp.vrp_series(iv30, garch)


def stats(trades) -> dict:
    r = np.array([t.return_on_risk for t in trades])
    return {"n": len(r), "mean": r.mean(), "wins": (r > 0).mean(), "total": r.sum(), "worst": r.min()}


def main() -> int:
    inputs = {s: vp.load_inputs(s) for s in VRP_POOLED_PARAMS}
    base = run(inputs)
    scenarios = {
        "base (frozen rules)": base,
        "costs x2 (charges + slippage)": run(inputs, st.scaled_rates(DEFAULT_RATES, 2),
                                             st.scaled_slippage(DEFAULT_SLIPPAGE, 2)),
        "slippage x3 (every leg)": run(inputs, slippage=st.scaled_slippage(DEFAULT_SLIPPAGE, 3)),
        **{f"start {k} month(s) later": run(inputs, start_after_months=k) for k in (1, 2, 3)},
    }
    print(f"All trades of the frozen rules, entries from {min(t.entry_date for t in base)}\n")
    print(f"{'scenario':34} {'trades':>6} {'mean/risk':>10} {'wins':>6} {'total':>8} {'worst':>7}  pass?")
    ok_all = True
    for name, trades in scenarios.items():
        s = stats(trades)
        ok = s["mean"] > 0
        ok_all &= ok
        print(f"{name:34} {s['n']:6d} {s['mean']:+10.2%} {s['wins']:6.0%} {s['total']:+8.2f} {s['worst']:+7.0%}  "
              f"{'PASS' if ok else 'FAIL'}")
    base_r = np.array([t.return_on_risk for t in base])
    shifted = [stats(scenarios[f"start {k} month(s) later"])["mean"] for k in (1, 2, 3)]
    similar = all(m > 0 for m in shifted) and min(shifted) > 0.5 * base_r.mean()
    print(f"\nStart shift: {', '.join(f'{m:+.2%}' for m in shifted)} vs base {base_r.mean():+.2%} -> "
          f"{'PASS' if similar else 'FAIL'} (same sign, at least half the size)")

    lo, hi = st.block_bootstrap_ci(base_r)
    print(f"Block bootstrap (10,000 runs, blocks of 5): 95% interval of the mean [{lo:+.2%}, {hi:+.2%}] -> "
          f"{'PASS' if lo > 0 else 'FAIL'} (must exclude 0)")
    dd95 = st.drawdown_monte_carlo(base_r)
    print(f"Drawdown (units of one condor's max risk): actual {st.max_drawdown_units(base_r):.2f}, "
          f"95th percentile of reorderings {dd95:.2f} -> {dd95 * RISK_PER_CONDOR:.2%} of capital at "
          f"{RISK_PER_CONDOR:.3%} per condor")

    crash = run({s: crash_inputs(s) for s in VRP_POOLED_PARAMS}, start="2019-06-01")
    crash = [t for t in crash if t.entry_date <= pd.Timestamp("2020-06-30").date()]
    print(f"\nCrash proxy (GARCH on 1 year of training; entries Jun-2019 to Jun-2020): {len(crash)} condors")
    for t in crash:
        print(f"  {t.symbol:9} entered {t.entry_date}  expiry {t.expiry}  exit {t.exit_date} ({t.exit_reason}): "
              f"{t.return_on_risk:+.0%} of risk")

    print(f"\nWorst events (every condor open in the window; capital at {RISK_PER_CONDOR:.3%} per condor):")
    event_ok = True
    for name, (a, b) in EVENTS.items():
        lo_d, hi_d = pd.Timestamp(a).date(), pd.Timestamp(b).date()
        pool = crash if "COVID" in name else base
        hit = [t for t in pool if t.entry_date <= hi_d and t.exit_date >= lo_d]
        loss = sum(min(t.return_on_risk, 0) for t in hit)
        worst = min((t.return_on_risk for t in hit), default=0.0)
        cap = loss * RISK_PER_CONDOR
        ok = worst >= -1.10 and -cap <= MAX_OPEN_RISK
        event_ok &= ok
        src = " (crash proxy)" if "COVID" in name else ""
        print(f"  {name}{src}: {len(hit)} condors, losses {loss:+.2f} x risk, worst {worst:+.0%} -> "
              f"{cap:+.2%} of capital  {'PASS' if ok else 'FAIL'}")
    print(f"\nSizing: up to {MAX_CONCURRENT} condors open at once -> each at most {RISK_PER_CONDOR:.3%} of capital "
          f"to stay within the {MAX_OPEN_RISK:.0%} open-risk cap")
    passed = ok_all and similar and lo > 0 and event_ok
    print(f"\nStage 2 verdict: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
