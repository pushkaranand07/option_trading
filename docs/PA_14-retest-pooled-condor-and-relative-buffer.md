# PA-14 — Re-tests of the two fixable rejections: pooled 4-book VRP condor (close), relative strength with a turnover buffer (still rejected)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/condor.py`, `tradingagents/analytics/vrp.py`, `tradingagents/analytics/ml/relative.py`, `tradingagents/analytics/prices.py`, `scripts/quant_vrp_condor.py`, `scripts/quant_relative.py`, `scripts/quant_daily_update.py`, `scripts/quant_daily_update.cmd`, `tests/test_quant_condor.py`, `tests/test_quant_vrp.py`, `tests/test_quant_relative.py`, `tests/test_quant_datastore.py`, `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-05](PA_05-garch-volatility-and-vrp-condor.md) (first VRP condor test), [PA-10](PA_10-relative-strength-model.md) (first relative-strength test), [PA-13](PA_11-ship-expected-move-and-daily-refresh.md) (scheduler fix, included in this PR), [PA-15](PA_15-proof-plan-move-size-and-paper-trading.md) (what came next), [PA-17](PA_17-backward-holdout-2015.md) (the holdout that later rejected the pooled condor), [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md), [architecture/14-option-strategy-simulators-and-costs.md](architecture/14-option-strategy-simulators-and-costs.md) |
| **Pull request** | #13 (branch `quant/retest-condor-relative`) |
| **Date** | 2026-10-23 |

Research and decision support only — not investment advice.

---

## 1. Problem

Two earlier strategies had been rejected for reasons that looked fixable rather than fatal:

- **VRP iron condor** ([PA-05](PA_05-garch-volatility-and-vrp-condor.md)). An iron condor sells a put spread and a call
  spread together, with losses capped by the long "wings". The VRP (volatility risk premium) version sells only when
  implied volatility is high relative to the GARCH forecast. It was rejected on NIFTY and BANKNIFTY because it made
  only 15–19 trades in 5 years; the gate needs at least 100 out-of-sample trades.
- **Relative strength** ([PA-10](PA_10-relative-strength-model.md)): a model that picks the stocks likely to beat the
  other 28. It was rejected on costs (−1.2% a year after costs), and its random baseline was unfair.

Each fix was declared before running, and every run counts toward the trial log.

## 2. Root cause / findings

- **Condor trade count.** One condor at a time per monthly expiry cannot reach 100 trades in five years.
- **Relative-strength costs.** Rebuilding the top-K book on every rebalance turned over many stocks, and each small
  ranking change cost a round trip.
- **Unfair baseline.** The old random baseline re-drew all K stocks every time and so paid more in costs than the model.
  This flattered the model ("beats random 99%"). A fair baseline must make exactly the model's number of swaps.
- **Prices one day behind.** The after-close refresh fetched NSE files for 23-Oct but Yahoo prices only to 22-Oct, so
  the regime lagged a day (commit `bdd3b00`).

## 3. Decisions

- **Condor fix: staggered books and pooling.** 4 staggered books, so a new monthly condor is opened about weekly (still
  monthly expiries). One verdict across NIFTY and BANKNIFTY together, capital split equally.
- **Relative-strength fix: a turnover buffer.** Hold a stock while it still ranks within the top K, instead of rebuilding
  the book.
- **Baseline made fair** before judging the buffer: random picks make exactly the model's swaps.
- **Next step after the condor result: paper trading, not more tuning** (PR #13 body). 72 condor variants had been run by
  then, and more tuning would only raise the trial count.
- User decisions in this PR: not recorded.

## 4. What was built / changed

| Change | Where | What it does |
|---|---|---|
| Staggered books | `condor.simulate_staggered` | N books; book *j* enters only in ISO weeks with `week % N == j`; together they enter about weekly into the same monthly expiries; each trade carries 1/N of its P&L |
| Pooling | `vrp.pool` | One verdict for several underlyings side by side (capital split); random runs paired and averaged; `n_trials` counts every grid point |
| Simulator speed-up | `condor.py` | Each option chain prepared once, strike choices memoised; identical results (NIFTY 2018–21: 65 trades, −6.91%); first run 11.3 s → 6.7 s, repeat runs 0.1 s |
| Script flags | `scripts/quant_vrp_condor.py` | `--books`, `--pool` |
| Turnover buffer | `relative.portfolio(keep=K)` | A held stock stays while it ranks within the top K |
| Turnover-matched random baseline | `ml/relative.py` | Random stocks with exactly the model's swaps per rebalance, never re-picking one just dropped |
| Script flag | `scripts/quant_relative.py` | `--keep`; every relative-strength variant counts toward the deflated Sharpe's number of trials |
| Today's bar after the close | `tradingagents/analytics/prices.py` | Prices include today's bar once the market has closed (16:00), else stop at yesterday |
| Scheduler fix | `scripts/quant_daily_update.*` | Carried in from #12 — see [PA-13](PA_11-ship-expected-move-and-daily-refresh.md) |

## 5. Tests

- Staggered books equal the four single books simulated one by one; each trade carries 1/N of its P&L.
- Pooling adds trades and averages returns.
- The random baseline makes exactly the model's swaps.
- The buffer trades less than rebuilding the book.
- Prices: today's bar is included only after 16:00 (`tests/test_quant_datastore.py`).
- Full suite: 1,548 passed; ruff clean.

## 6. Results

**Pooled 4-book VRP condor (NIFTY + BANKNIFTY, 2021-04 → 2026-05 out of sample)**

| Measure | Result | Gate |
|---|---|---|
| Trades | 84 | ≥ 100 — **missed** |
| Win rate | 87% | — |
| Mean return | +12.7% of max risk per trade | — |
| OOS Sharpe (in-sample) | 0.65 (1.04) | OOS/IS ≥ 0.5 — met |
| Beats random entry days | 100% of runs | — |
| Regimes | profitable in all 3 | met |
| Deflated Sharpe (36 trials counted) | 0.934 | ≥ 0.95 — **missed** |
| Positive folds | 60% | ≥ 70% — **missed** |
| Parameter stability | 0.41 | ≥ 0.5 — **missed** |
| "Enter whenever possible" baseline | Sharpe −0.35 | — |

Verdict: **still rejected**, but the strongest candidate so far — recorded as a paper-trade candidate.

**Relative strength with a turnover buffer**

| Measure | Result |
|---|---|
| Trades | 695 → 286 (−59%) |
| Excess return | −1.0% a year after costs |
| Same-day AUC | 0.510 |
| Beats turnover-matched random | 94% |
| Deflated Sharpe | 0.43 |

Verdict: **still rejected.** The picks do not beat the average.

## 7. Verification

- Both re-tests were run on the real NSE store with costs and slippage; results recorded in
  [PROGRESS_TRACKER.md](PROGRESS_TRACKER.md) (commit `c394dd5`).
- The simulator speed-up was checked by reproducing the earlier NIFTY 2018–21 result exactly (65 trades, −6.91%).

## 8. Risks and open items

- The pooled condor missed four gates; its parameters were unstable across folds (stability 0.41).
- Trial count keeps rising (72 condor variants by this point), which lowers the deflated Sharpe of anything found later.
- Follow-up: the condor was frozen and sent to paper trading in [PA-15](PA_15-proof-plan-move-size-and-paper-trading.md),
  stress-tested in [PA-16](PA_16-stage2-stress-tests.md), and **rejected by the backward holdout** in
  [PA-17](PA_17-backward-holdout-2015.md).
