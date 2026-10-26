# PA-13 — Backward holdout 2015–21 rejects the VRP condor; paper trading kept as observation only

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/holdout.py`, `scripts/quant_holdout.py`, `tradingagents/analytics/paper.py`, `tradingagents/analytics/paper_strategies.py`, `scripts/quant_paper.py`, `tests/test_quant_holdout.py`, `tests/test_quant_paper.py`, `docs/PROOF_PLAN.md`, `docs/strategies/vrp_condor_pooled.md`, `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-12](PA_12-stage2-stress-tests.md) (Stage 2, included in this PR), [PA-11](PA_11-proof-plan-move-size-and-paper-trading.md) (spec and ledger), [PA-10](PA_10-retest-pooled-condor-and-relative-buffer.md), [PA-03](PA_03-quant-foundation-nse-data-store.md) (downloader and store), [plans/PROOF_PLAN.md](plans/PROOF_PLAN.md), [strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md), [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md), [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) |
| **Pull request** | #16 (branch `quant/holdout-2015`; builds on #15 — merging it merged both) |
| **Date** | 2026-10-23 |

Research and decision support only — not investment advice.

---

## 1. Problem

The frozen VRP condor's settings were chosen from 2021–2026 walk-forward folds. Its good backtest and stress tests all
used those same years. The question: do the unchanged rules work on years that choice never saw?

## 2. Root cause / findings

The earlier years (2015 to March 2021) never informed the settings, so running the unchanged rules there is a
one-trial holdout. It needed 1,473 newly downloaded NSE files (F&O bhavcopy and index closes for 2015–2017). Entries
2015-08 → 2021-04.

| | NIFTY | BANKNIFTY | Pooled |
|---|---|---|---|
| Trades | 35 | 60 | 95 |
| Mean return on max risk | +1.09% | −9.45% | **−5.57%** |
| Wins | 74% | 67% | 69% |

- Bootstrap 95% interval of the mean: [−16.1%, +5.5%].
- Beats random entry days in **60%** of 200 runs (needs 95%).
- "Enter whenever possible" baseline: −5.0%.
- All 190 frozen-rule trades (holdout + 2021–26): mean +2.7%, 95% interval [−4.3%, +8.7%] — includes 0.

**Finding:** on unseen years the VRP filter did no better than random timing. The 2021–26 result did not carry over.

## 3. Decisions

- **VRP condor rejected** (2026-10-23).
- **Paper trading kept as observation only (user).** The strategy is tracked for information, never reported as
  passing, never fails the daily job, and is not eligible for live trading on this evidence.
- **Holdout built apart from production:** everything is built in memory; the production store and the paper ledger
  are untouched.

## 4. What was built / changed

| Part | What it does |
|---|---|
| `analytics/holdout.py` | Builds the holdout inputs in memory; runs the frozen rules; keeps only entries up to the end date; reports baselines and the combined frozen-rules record for the trade-count gate |
| `scripts/quant_holdout.py` | Runs the holdout |
| `paper.PaperStrategy.status` / `note` | New "observation" status: tracked, never reported as passing, never fails the daily job |
| `paper_strategies.py`, `scripts/quant_paper.py` | VRP condor marked observation only |
| Spec, proof plan, tracker | Holdout table, status **REJECTED**, schedule updated |

## 5. Tests

- Holdout runner keeps only entries up to the end date and reports baselines (`tests/test_quant_holdout.py`).
- An observation-only strategy is never reported as passing (`tests/test_quant_paper.py`).
- Full suite: 1,562 passed; ruff clean.

## 6. Results

**Backward holdout: FAIL → the pooled VRP condor is rejected.** After this, no trading signal had passed its tests;
GARCH and the regime model remain in use as risk inputs only.

## 7. Verification

- Run on real NSE files for 2015–2021, in memory; the production store and paper ledger were not modified.
- Results recorded in [strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md),
  [plans/PROOF_PLAN.md](plans/PROOF_PLAN.md) and [PROGRESS_TRACKER.md](PROGRESS_TRACKER.md).

## 8. Risks and open items

- The observation ledger starts Mon 2026-10-26; with ~17 trades a year it will take a long time to say anything.
- The Stage 3 targets apply only to a candidate that has passed its backtest; none exists, so they are on hold.
- The next candidate is expected to come from a new Stage 0 spec (the proof plan names the user's own idea as most
  promising).
