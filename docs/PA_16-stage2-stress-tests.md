# PA-16 — Stage 2 stress tests for the pooled VRP condor: pass, weak spot found

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/stress.py`, `tradingagents/analytics/condor.py` (`offset` parameter), `scripts/quant_stress.py`, `tests/test_quant_stress.py`, `docs/PROOF_PLAN.md`, `docs/strategies/vrp_condor_pooled.md`, `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-15](PA_15-proof-plan-move-size-and-paper-trading.md) (proof plan and frozen spec), [PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md), [PA-17](PA_17-backward-holdout-2015.md) (next test), [plans/PROOF_PLAN.md](plans/PROOF_PLAN.md), [strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md), [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md), [architecture/14-option-strategy-simulators-and-costs.md](architecture/14-option-strategy-simulators-and-costs.md) |
| **Pull request** | #15 (branch `quant/stage2-stress`) |
| **Date** | 2026-10-23 |

Research and decision support only — not investment advice.

---

## 1. Problem

Stage 2 of the [proof plan](plans/PROOF_PLAN.md) says a frozen strategy must survive attempts to break its backtest
before forward paper trading counts. The pooled VRP condor
([strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md)) had passed through Stage 0 (spec frozen) but had
not been stress-tested.

## 2. Root cause / findings

All figures are mean return per trade as a % of the condor's max risk, on the frozen rules (base +11.05%).

| Test | Pass mark (proof plan) | Result |
|---|---|---|
| Costs ×2 (charges + slippage) | still profitable | **+9.71%** |
| Slippage ×3 on every leg | still profitable | **+9.62%** |
| Start 1 / 2 / 3 months later | same sign, similar size | **+10.96% / +10.82% / +10.33%** |
| Block bootstrap, 95% interval of the mean | excludes 0 | **[+6.67%, +15.17%]** |
| Trade-order Monte Carlo, 95th-percentile drawdown | fits the kill rule | 1.54 × one condor's max risk = **0.58% of capital** at 0.375% per condor |
| Adani (Jan–Feb 2023) / election day (Jun 2024) | loss per event within limits | 1 / 7 condors open, **no losses** |
| COVID 2020 (crash proxy, stress only) | loss per event within limits | 1 condor in the crash window, stopped at −33%; **then two max losses (−96%, −101%) in the May–June 2020 V-rebound**; all 7 condors Jun-2019 → Jun-2020 sum to −1.73 × max risk (≈ −0.65% of capital) |

The COVID test is a proxy: GARCH was trained on only 1 year so the signal exists in 2020. It is for stress only.

**Weak spot found:** a sharp V-shaped rebound while implied volatility is still high. The signal says "sell premium"
just as the market rips through the call wing. The loss stays within the risk limits.

## 3. Decisions

- **Sizing fixed:** up to 8 condors can be open at once (2 indices × 4 books), so each is capped at **0.375% of
  capital** (8 × 0.375% = the 3% open-risk cap). Written into the spec and the proof plan.
- **Correction:** a first "start shift" test relabelled the books' weeks; it was degenerate by construction and was
  replaced with real delayed starts (a new `offset` parameter on the staggered simulator).
- **Spec commentary corrected:** the Stage 3 timeline in the spec is the measured ~21 months, not the early estimate
  (commit `05f43f9`).
- User decisions in this PR: not recorded.

## 4. What was built / changed

| Part | What it does |
|---|---|
| `analytics/stress.py` | Scaled costs and slippage, block bootstrap confidence interval, trade-order drawdown Monte Carlo |
| `scripts/quant_stress.py` | Runs every scenario on the frozen rules |
| `condor.py` | `offset` parameter so books can start later |
| Spec, proof plan, tracker | Stage 2 results table, sizing rule, known weakness |

## 5. Tests

`tests/test_quant_stress.py`:
- Doubled rates double every charge.
- The bootstrap interval brackets the mean and excludes 0 for a clear edge.
- Drawdown arithmetic in risk units.

Staggered-book tests still pass with the new `offset` parameter; ruff clean. Full-suite count: not recorded.

## 6. Results

**Stage 2: PASS**, with one known weakness (V-shaped rebounds after a crash). The strategy stayed at Stage 3 paper
trading.

## 7. Verification

Every scenario was run on the real NSE store with the frozen rules (`scripts/quant_stress.py`); results recorded in
[strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md) and [PROGRESS_TRACKER.md](PROGRESS_TRACKER.md).

## 8. Risks and open items

- Stress tests reuse the same 2021–26 history the settings were chosen on; they test robustness, not new data.
- The rebound weakness was to be watched in paper trading.
- Follow-up: the backward holdout on 2015–21 ([PA-17](PA_17-backward-holdout-2015.md)) **failed** and rejected the
  strategy.
