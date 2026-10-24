"""Results-day iron butterfly on the 29 stocks (spec frozen in docs/strategies/results_iron_fly.md).

    python scripts/quant_results_fly.py
    python scripts/quant_results_fly.py --symbols INFY TCS --random-runs 50

Downloads each stock's board meetings from NSE once (cached with the raw NSE
files), simulates every results event 2018 → today, and judges it with the tests
fixed in the spec: >= 100 trades, bootstrap interval above 0, beats the same trade
on random quiet days in >= 95% of runs, positive in >= 70% of years, deflated
Sharpe >= 0.95 counting every logged trial. Trades are saved to
<store>/events/results_fly_trades.csv; the run goes in the trial log.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.analytics import datastore as ds, events as ev, stress as st, trial_log  # noqa: E402
from tradingagents.analytics.condor import _prepare  # noqa: E402
from tradingagents.analytics.universe import STOCKS  # noqa: E402
from tradingagents.analytics.validation import deflated_sharpe_ratio  # noqa: E402

IDEA = "results_iron_fly"


def lots_of(symbol: str) -> pd.Series:
    fo = ds.load("fo_summary", symbols=[symbol])
    s = pd.Series(fo["lot_size"].to_numpy(float), index=pd.to_datetime(fo["trade_date"]).dt.date)
    return s[~s.index.duplicated()].sort_index()


def random_returns(prep: dict, symbol: str, lots: pd.Series, trades: list, event_dates: list, runs: int,
                   rng: np.random.Generator) -> np.ndarray:
    """(runs, len(trades)) returns of the same fly on random quiet days: same year, same hold."""
    days = prep["days"]
    pos = {d: i for i, d in enumerate(days)}
    quiet = np.array(ev.quiet_entries(days, event_dates))
    years = np.array([days[i].year for i in quiet])
    memo: dict[tuple[int, int], float] = {}

    def trade_at(i: int, hold: int) -> float:
        key = (i, hold)
        if key not in memo:
            t = ev.window_trade(prep, symbol, lots.get(days[i], np.nan), days[i], days[i + hold])
            memo[key] = t.return_on_risk if t is not None else np.nan
        return memo[key]

    out = np.full((runs, len(trades)), np.nan)
    for j, t in enumerate(trades):
        hold = pos[t.exit_date] - pos[t.entry_date]
        pool = quiet[(years == t.entry_date.year) & (quiet + hold < len(days))]
        if not len(pool):
            continue
        for r in range(runs):
            for _ in range(5):                   # a few redraws if the fly can't be built that day
                v = trade_at(int(rng.choice(pool)), hold)
                if np.isfinite(v):
                    out[r, j] = v
                    break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", nargs="+", default=list(STOCKS))
    parser.add_argument("--random-runs", type=int, default=200)
    args = parser.parse_args()

    started = time.monotonic()
    rng = np.random.default_rng(0)
    trades, randoms, n_events = [], [], 0
    for symbol in args.symbols:
        events = ev.results_events(ev.fetch_board_meetings(symbol))
        n_events += len(events)
        chain = ds.load("option_chain", symbols=[symbol])
        lots = lots_of(symbol)
        got = ev.event_trades(chain, lots, events, symbol)
        trades += got
        randoms.append(random_returns(_prepare(chain), symbol, lots, got, list(events["date"]),
                                      args.random_runs, rng))
        print(f"  {symbol}: {len(events)} results dates, {len(got)} trades "
              f"({(time.monotonic() - started) / 60:.1f} min)", flush=True)

    trades.sort(key=lambda t: t.entry_date)
    r = np.array([t.return_on_risk for t in trades])
    rand = np.concatenate(randoms, axis=1)
    rows = pd.DataFrame([{k: v for k, v in asdict(t).items() if k not in ("strikes", "entry_prices", "exit_prices")}
                         | {"return_on_risk": t.return_on_risk, "strikes": t.strikes} for t in trades])
    out = ds.store_root() / "events"
    out.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out / "results_fly_trades.csv", index=False)

    n = len(r)
    lo, hi = st.block_bootstrap_ci(r)
    # The random runs are in each symbol's own event order; compare run means (same trades count per run).
    rand_means = np.nanmean(rand, axis=1)
    beats = float((r.mean() > rand_means).mean())
    by_year = pd.Series(r, index=[t.entry_date.year for t in trades]).groupby(level=0).mean()
    n_trials = trial_log.trial_count() + 1
    dsr = deflated_sharpe_ratio(r, n_trials, sr_variance=1 / max(n - 1, 1))
    wins = float((r > 0).mean())

    tests = [
        ("Trades >= 100", n >= 100, f"{n} (of {n_events} results dates)"),
        ("Mean > 0, bootstrap 95% CI above 0", lo > 0, f"mean {r.mean():+.2%}, CI [{lo:+.2%}, {hi:+.2%}]"),
        ("Beats random quiet days >= 95%", beats >= 0.95,
         f"{beats:.0%} of {len(rand_means)} runs (random mean {np.mean(rand_means):+.2%})"),
        ("Positive years >= 70%", (by_year > 0).mean() >= 0.70, f"{(by_year > 0).sum()}/{len(by_year)}"),
        ("Deflated Sharpe >= 0.95", dsr >= 0.95, f"{dsr:.3f} (N = {n_trials} trials)"),
    ]
    print(f"\nResults-day iron butterfly, {trades[0].entry_date} -> {trades[-1].exit_date}: "
          f"{n} trades, wins {wins:.0%}, median {np.median(r):+.2%}, worst {r.min():+.2%}")
    print("\nBy year (mean return on max risk):")
    print(by_year.map(lambda v: f"{v:+.2%}").to_string())
    print()
    for name, ok, detail in tests:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    verdict = "pass" if all(ok for _, ok, _ in tests) else "reject"
    print(f"\nVerdict: {verdict.upper()}")
    trial_log.record(trial_log.Trial(
        idea=IDEA, params={"wing_mult": ev.DEFAULT_FLY.wing_mult, "max_dte": ev.DEFAULT_FLY.max_dte},
        universe="29 F&O stocks", data_start=str(trades[0].entry_date), data_end=str(trades[-1].exit_date),
        n_trials=1, n_oos_trades=n, dsr=dsr, verdict=verdict,
        notes=f"mean {r.mean():+.4f}/risk, CI [{lo:+.4f}, {hi:+.4f}], beats random {beats:.0%}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
