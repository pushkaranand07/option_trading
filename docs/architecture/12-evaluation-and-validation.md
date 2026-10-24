# Evaluation and validation

> **Status:** Current.
> **Scope:** `tradingagents/analytics/evaluate.py`, `gates.py`, `validation.py`, `trial_log.py`, `stress.py`,
> `holdout.py`, `swings.find_lookahead`; `scripts/quant_evaluate.py`, `scripts/quant_stress.py`,
> `scripts/quant_holdout.py`.
> **Last verified against the code:** 2026-10-24

Research only, not investment advice.

---

## 1. The idea

Try enough ideas on the same history and one will look brilliant by luck. These modules make every signal face the
same tests, with the bar fixed before results are seen, and count every attempt. The ladder from backtest to live
trading is [../plans/PROOF_PLAN.md](../plans/PROOF_PLAN.md) (section 6 below).

## 2. The Phase 2 harness — `evaluate.py`

**Data shape.** A wide frame indexed by session with `(field, symbol)` columns, built by `panel()` from the prices
table. Opens, highs and lows are put on the same dividend-adjusted basis as `adj_close`.

**Signal contract.** `signal(data, params) -> DataFrame` of target positions in [−1, 1]. The position for session *t*
may use rows strictly before *t*.

**Execution.** A position for *t* is entered at *t*'s open; its return runs open(*t*) → open(*t+1*). This is when a
manual trader can act on post-close data.

**Costs.** Each change in position pays half a round trip (`costs.cost_fraction`) per unit changed. The cost fraction
depends on the position size because brokerage is flat, so `position_value` (₹ per position) is a **required**
argument — the user sets it, nothing assumes it.

**Walk-forward.** Defaults `TRAIN = 756` sessions (3 years), `TEST = 126` (6 months), `EMBARGO = 20`. For each fold
every grid point is scored on the training window; the best training Sharpe is used on the following test window,
warmed up on the training data. Only the stitched out-of-sample positions are judged; costs are charged over the
stitched span, so fold boundaries pay for real position changes.

**Outputs** (`Evaluation`): trade ledger (`Trade`: symbol, direction, entry, exit, sessions, net return), trade stats
(hit rate, average win / loss, payoff, expectancy after costs), in-sample and out-of-sample Sharpe, deflated Sharpe,
verdict, per-year table, per-regime mean trade return, and the gate report. Every run is written to the trial log.

**Leak check.** `same_bar_leaks` samples 25 sessions. For each, the position computed on data cut after *t* must equal
the full-history one (no future rows), and must not move when row *t*'s numbers are scrambled (no same-session data).
`swings.find_lookahead` does the same for chart-pattern signals by recomputing on truncated data.

**Baselines** on the same out-of-sample days and costs:

| Baseline | What it is |
|---|---|
| `buy_and_hold` | Long every symbol all the time |
| `ma_50_200` | Long when the 50-session average is above the 200-session one (lagged a session) |
| Random entry | `random_entry_sharpes`: the same trades (symbol, direction, length) at random start dates, 1,000 runs by default. The strategy must beat at least 95% of them |

The harness's own exit gate (Phase 2) was that a random signal comes out rejected and a planted edge is found; both
held on synthetic and real data (tracker).

## 3. The eight gates — `gates.py`

Fixed in `Gates` before any result (plan, Phase 0). A gate whose evidence was not supplied is `not_evaluated`, which is
**not** a pass. The verdict is `approved` only when every gate was checked and passed, `rejected` if any failed,
otherwise `incomplete`.

| # | Gate | Threshold |
|---|---|---|
| 1 | No look-ahead | 0 mismatches |
| 2 | Out-of-sample trades | ≥ 100 |
| 3 | Deflated Sharpe | ≥ 0.95 |
| 4 | OOS / IS Sharpe | ≥ 0.5 (below: the in-sample result is mostly fit); fails if in-sample Sharpe ≤ 0 |
| 5 | Positive folds | ≥ 70% of walk-forward test windows positive after costs |
| 6 | Drawdown vs return | \|max drawdown\| ≤ 2× annual return; fails if annual return ≤ 0 |
| 7 | Regime stability | positive in ≥ 2 regimes, or explicitly switched off in every regime where it loses |
| 8 | Parameter stability | median neighbour Sharpe / chosen Sharpe ≥ 0.5 (neighbours: one grid step away in one parameter) |

In the harness the stability ratio is computed per fold on its own training window and their mean is passed against a
chosen value of 1.

## 4. Statistics — `validation.py`

| Function | What it gives |
|---|---|
| `walk_forward_splits` | Rolling (train, test) windows by position, with an embargo gap |
| `sharpe` | Annualised Sharpe (252 periods) |
| `probabilistic_sharpe_ratio` (PSR) | Probability the true Sharpe beats a benchmark, given sample length, skew and kurtosis |
| `expected_max_sharpe` | The best Sharpe luck alone would produce over N trials |
| `deflated_sharpe_ratio` | PSR against that expected maximum (Bailey & López de Prado, 2014); the spread of trial Sharpes sets how high luck reaches |
| `evidence_verdict` | `insufficient_evidence` below `MIN_TRADES = 30`; otherwise `significant` if DSR ≥ `DSR_SIGNIFICANT = 0.95`, else `not_significant` |
| `walk_forward` | Generic walk-forward over a returns-producing strategy |

Only the standard library's `NormalDist` is used (no SciPy).

## 5. Trial log — `trial_log.py`

Every backtest run writes one row to SQLite at `<data_cache_dir>/quant/trial_log.sqlite`: idea, parameters (JSON),
universe, data span, grid size (`n_trials`), out-of-sample trades, IS / OOS Sharpe, DSR, verdict, gate verdict, notes.
`trial_count()` sums the grid sizes and is the honest N for the next deflated Sharpe. The proof plan recorded 16 runs
and 178 parameter combinations on 2026-10-23; the results-fly tests later used N = 183 and N = 184
([../strategies/results_iron_fly.md](../strategies/results_iron_fly.md),
[../strategies/results_iron_fly_overpriced.md](../strategies/results_iron_fly_overpriced.md)).

The agents' quant report reads the latest row of each idea to show its verdict
([16](16-quant-context-in-agents.md)).

## 6. Stress tests — `stress.py`

Pure functions over a frozen strategy's trade results (fractions of max risk); the scenarios run in
`scripts/quant_stress.py`.

| Function | Use |
|---|---|
| `scaled_rates(rates, factor)` | Every charge × factor (GST rate unchanged; it applies to the scaled charges) |
| `scaled_slippage(slip, factor)` | Slippage × factor |
| `block_bootstrap_ci` | 95% interval of the mean, resampling blocks of 5 consecutive trades, 10,000 runs |
| `max_drawdown_units` / `drawdown_monte_carlo` | Worst drawdown of the running sum, and its 95th percentile over random trade orders |

The pooled VRP condor passed Stage 2 on 2026-10-23 (costs ×2: +9.71% of risk per trade vs base +11.05%; bootstrap
interval [+6.67%, +15.17%]); the weak spot found was a V-shaped rebound while IV is still high. Full table in
[../strategies/vrp_condor_pooled.md](../strategies/vrp_condor_pooled.md).

## 7. Backward holdout — `holdout.py`

The frozen VRP settings were the walk-forward's most frequent choice over 2021-04 → 2026 test folds. The years before
never informed that choice, so running the frozen rules there unchanged is a one-trial holdout.

- Built **in memory**: 2015–2017 from raw NSE files (F&O bhavcopy, official index closes), 2018 on from the store, and
  Yahoo index prices back to 2012 for GARCH training. The production store, its forecasts and the paper ledger are
  not touched.
- `run()` simulates the frozen rules, an "always enter" baseline and 200 random-entry runs at the same entry rate, and
  a block-bootstrap interval of the mean.

Result (2026-10-23): pooled 95 trades, −5.57% of risk per trade, beats random entry in 60% of runs (needs 95%) →
**rejected**. Paper trading continues as observation only.

## 8. The proof-plan stages

From [../plans/PROOF_PLAN.md](../plans/PROOF_PLAN.md). A strategy climbs one stage at a time and falls off when it fails one.

| Stage | Test | Code |
|---|---|---|
| 0 — Freeze the rules | Full spec committed in `docs/strategies/<name>.md` before testing; any change is a new strategy | [../strategies/](../strategies/vrp_condor_pooled.md) |
| 1 — Backtest gates | Walk-forward, out of sample, after costs, vs random and "always trade" | `evaluate.py`, `vrp.py`, `gates.py` |
| 2 — Stress tests | Costs ×2, wing slippage ×3, worst periods, block bootstrap, trade-order Monte Carlo, start-date shift | `stress.py`, `scripts/quant_stress.py` |
| 3 — Forward paper trading | Frozen rules on data that did not exist when they were written; ≥ 30 trades, p < 0.05 | `paper.py` ([15](15-daily-refresh-and-paper-trading.md)) |
| 4 — Small live on Dhan | 0.5% risk per trade, ≤ 3% open; the user places every order | not built (on hold) |
| 5 — Scale up | 0.5% → 0.75% → 1%, one step per 100 live trades inside the band | not built (on hold) |

Related: [14 — option strategy simulators](14-option-strategy-simulators-and-costs.md),
[10 — overview](10-quant-layer-overview.md).
