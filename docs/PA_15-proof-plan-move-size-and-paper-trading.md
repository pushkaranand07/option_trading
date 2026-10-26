# PA-15 — Proof plan, approach A (predict move size), quiet-stock condor rejected, VRP spec frozen, paper-trading ledger

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `docs/PROOF_PLAN.md` (now [plans/PROOF_PLAN.md](plans/PROOF_PLAN.md)), [strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md), `tradingagents/analytics/ml/move_size.py`, `tradingagents/analytics/ml/inputs.py`, `tradingagents/analytics/quiet_condor.py`, `tradingagents/analytics/paper.py`, `tradingagents/analytics/paper_strategies.py`, `tradingagents/analytics/condor.py`, `tradingagents/analytics/vrp.py`, `scripts/quant_move_size.py`, `scripts/quant_quiet_condor.py`, `scripts/quant_paper.py`, `scripts/quant_vrp_condor.py`, `scripts/quant_daily_update.py`, tests for each, `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md) (the re-test that made the condor a candidate), [PA-09](PA_09-agent-quant-tool-and-lightgbm.md) (LightGBM), [PA-11](PA_11-ship-expected-move-and-daily-refresh.md) (daily refresh), [PA-13](PA_11-ship-expected-move-and-daily-refresh.md), [PA-16](PA_16-stage2-stress-tests.md), [PA-17](PA_17-backward-holdout-2015.md), [plans/PROOF_PLAN.md](plans/PROOF_PLAN.md), [strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md), [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md), [architecture/13-volatility-and-regime-models.md](architecture/13-volatility-and-regime-models.md), [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) |
| **Pull request** | #14 (branch `quant/move-size`; builds on #12 and #13 — merging it merged all three) |
| **Date** | 2026-10-23 |

Research and decision support only — not investment advice.

---

## 1. Problem

- There was no written rule for when a strategy that "looks good in a backtest" may be traded on Dhan with real money.
- Every direction model so far ("will it rise", "will it beat the others") had no edge. An open question was whether
  the *size* of a move is easier to predict than its direction.
- The pooled VRP condor ([PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md)) was the strongest candidate but
  missed the 100-trade gate; only future data can supply more trades.

## 2. Root cause / findings

**Approach A, step 1 — predict move size per stock** (declared before testing, commit `0904ec9`).
Label: the 10-session move is bigger than 1× the stock's expected move (trailing 60-session vol × √10). Scored by
same-day AUC (ranking stocks against each other on the same day) and against ranking by the GARCH forecast alone.

| Ranker | Same-day AUC |
|---|---|
| LightGBM move-size model | **0.503** — no skill; it leaned on market-wide features |
| GARCH forecast alone | **0.573** — ranks which stocks will move big |

**Approach A, step 2 — iron condors on the 5 stocks GARCH predicts quietest** (commit `f8f429f`).
Every 10 sessions, rank by GARCH 10-session forecast ÷ trailing vol; open a monthly condor (short delta 0.20, 4%
wings, take profit at 50% of credit, stop at 2× credit) on the 5 lowest. Baselines: 5 random stocks (paired runs) and
all stocks. Settled on NSE futures closes. One trial (the GARCH ranking was not fitted to this question).

| | Sharpe |
|---|---|
| 5 GARCH-quietest stocks | **−0.44** |
| 5 random stocks | −0.84 |
| All stocks | −1.22 |

GARCH's picks beat random in 92% of runs, but stock condors lose money overall: GARCH only makes them lose less.
Robustness runs at delta 0.15 / 0.25 were part of the design; their figures are not recorded in the PR.

## 3. Decisions

- **Proof plan approved (user).** An evidence ladder from backtest to Dhan, with kill rules and risk limits fixed in
  advance ([plans/PROOF_PLAN.md](plans/PROOF_PLAN.md)).
- **Move size: use GARCH, not LightGBM.** GARCH's ranking (0.573) is kept as a risk input; the LightGBM model is not.
- **Quiet-stock condor rejected** (Sharpe −0.44).
- **VRP condor spec frozen** (Stage 0) using the walk-forward's most frequent setting per index (6 of 10 folds each).
- **Paper trading is the decisive test** for the VRP condor, because forward data cannot be overfit.
- **Further LightGBM work and the MA trend rule dropped (user)** — exit gate not met (AUC 0.506 < 0.55). They come back
  only if the user asks.

## 4. What was built / changed

**Proof plan — the evidence ladder**

| Stage | What | Pass |
|---|---|---|
| 0 | Freeze the rules in `docs/strategies/<name>.md`, commit to git | spec committed |
| 1 | Backtest gates (walk-forward, costs, baselines) | the eight gates |
| 2 | Stress tests | costs ×2, slippage ×3, worst periods, bootstrap, drawdown, start shift |
| 3 | Forward paper trading | mean > 0 with p < 0.05 on ≥ 30 forward trades; no kill rule hit |
| 4 | Small live on Dhan, user places every order | 0.5% risk per trade, ≤ 3% open risk; ≥ 3 months and 30 trades |
| 5 | Slow scale-up | 0.5% → 0.75% → 1% hard cap, one step per 100 live trades |

**Frozen VRP condor spec** ([strategies/vrp_condor_pooled.md](strategies/vrp_condor_pooled.md)): NIFTY short delta
0.25, 4% wings, z > 1.5; BANKNIFTY short delta 0.15, 4% wings, z > 0.5; 4 staggered books; 50% take profit, 2× credit
stop, both filled at the next session's close.

**Paper-trading ledger**

| Part | What it does |
|---|---|
| `analytics/paper.py` | Each night re-runs the frozen simulation on all data and records trades from the start date. A recorded trade that changes or vanishes is an **integrity event**. Kill rules: running result below the 5th-percentile band, 8 losses in a row, a loss beyond max risk. Pass needs ≥ 30 forward trades and p < 0.05 |
| `analytics/paper_strategies.py` | The VRP condor from **Mon 2026-10-26**; expected range measured on the frozen rules (95 trades: +11.1% mean, 20% spread of max risk) |
| `condor.simulate(include_open=True)` | Open trades are reported so the ledger can follow them to exit |
| `vrp.load_inputs` | Shared by the backtest and the paper ledger |
| `scripts/quant_paper.py` | Runs the ledger; added as the **last step** of the daily refresh |

## 5. Tests

- Ledger records only from the start date; open trades close later.
- A recorded trade that changes or vanishes is an integrity event.
- Kill-rule and evidence arithmetic.
- Daily refresh step order includes paper trading last (`tests/test_quant_daily.py`).
- Move size: constant volatility → AUC ≈ 0.50; wandering volatility → 0.57 with every fold > 0.53.
- Quiet condor: picks are the lowest scores on each rebalance date; run combines stocks and baselines.
- Full suite: 1,557 passed; ruff clean.

## 6. Results

| Item | Verdict |
|---|---|
| LightGBM move size | no skill (AUC 0.503) |
| GARCH move-size ranking | ranks move size (AUC 0.573) → in use as a risk input |
| Quiet-stock condor | **rejected** (Sharpe −0.44) |
| Pooled VRP condor | frozen; sent to Stage 3 as a **paper-only** candidate (the plan lets a strategy short on trades get them from the future; it may not go live until Stage 3 supplies them) |

## 7. Verification

- Real run of the ledger: empty until 2026-10-26. Two open BANKNIFTY condors predate the start date and are excluded.
- Stage 3 timeline estimate in the proof plan: 14 trades by the formula, raised to the plan's floor of 30; ~17 trades a
  year → **~21 months** (corrected from an earlier estimate in commit `05f43f9`, PR #15).

## 8. Risks and open items

- The VRP condor's frozen setting is the modal one; the walk-forward's choice moved between folds, so forward results
  may differ from the backtest more than usual.
- Rare signal: ~21 months of paper trading needed.
- The proof plan said the quiet-stock condor was the best hope for a faster answer; it was rejected in the same PR.
- Follow-up: Stage 2 stress tests in [PA-16](PA_16-stage2-stress-tests.md); the backward holdout in
  [PA-17](PA_17-backward-holdout-2015.md) rejected the VRP condor and turned paper trading into observation only.
