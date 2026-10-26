# PA-05 — GARCH volatility forecasts, implied vol, and the VRP iron condor test (quant Phase 3)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | Part 1: `tradingagents/analytics/volatility_model.py`, `tradingagents/analytics/implied_vol.py`, `scripts/quant_vol_forecasts.py`, `tests/test_quant_{volatility,implied_vol}.py`. Part 2: `tradingagents/analytics/condor.py`, `tradingagents/analytics/vrp.py`, `costs.fill_charges`, `scripts/quant_vrp_condor.py`, `tests/test_quant_{condor,vrp}.py` |
| **Related** | [PA-04](PA_04-evaluation-harness-and-baselines.md) · [PA-08](PA_08-regime-detection-hmm.md) · [PA-09](PA_09-agent-quant-tool-and-lightgbm.md) · [PA-10](PA_10-relative-strength-model.md) · [PA-11](PA_11-ship-expected-move-and-daily-refresh.md) · [PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md) · [PA-17](PA_17-backward-holdout-2015.md) · [PA-20](PA_20-chronos-pretrained-model.md) · [architecture/13-volatility-and-regime-models.md](architecture/13-volatility-and-regime-models.md) · [architecture/14-option-strategy-simulators-and-costs.md](architecture/14-option-strategy-simulators-and-costs.md) |
| **Pull request** | #4 (branch `quant/phase-3-garch`), commit `a98625c` (part 1). Part 2 (`9d5941a`, `29b95c3`) and the GARCH convergence fix (`a99eca7`) were merged through #7 (branch `quant/phase-4-regime`) |
| **Date** | 2026-10-23 |

---

## 1. Problem

Direction is hard to predict; volatility is the part of markets that is reasonably predictable. The plan's Phase 3:
forecast volatility, check the forecast beats simple history, then test whether option premium is "rich" versus
that forecast — the volatility risk premium (VRP: implied vol minus forecast vol) — and whether selling it with an
iron condor (sell a put spread and a call spread together; losses capped by the wings) earns money after costs.

## 2. Root cause / findings

- NSE publishes only end-of-day option closes, so implied vol (IV) has to be backed out of closing prices; the free
  data has no bid/ask.
- NIFTY's computed 30-day IV tracks India VIX about 1 point below (attributed to skew; PR body).

## 3. Decisions

- **Models:** GARCH, GJR-GARCH (falls hurt more than rises) and EGARCH, Student-t errors; forecasts of 5, 10 and 21
  session volatility. Expanding window, refit weekly, recursion updated daily. Baselines: 20-day historical vol and
  EWMA. Scored with QLIKE (a loss that punishes under-forecasting more) with Newey-West t-statistics.
- **IV method (VIX-style):** forward from put-call parity, Black-76 IV of the traded ATM call/put, 30-day constant
  maturity by total-variance interpolation; untraded and expiry-day contracts skipped.
- **Condor rules (user):** monthly expiry, take profit at 50% of credit, stop at 2× credit (tracker: "your rules").
  Indices only, monthly (tracker: "you chose monthly indices").
- **Condor mechanics:** nearest monthly expiry 20–45 days out; short strikes by Black-76 delta on the parity forward;
  wings by % width; take-profit / stop seen at the close and filled next session; expiry settled at intrinsic against
  the index close, with exercise STT; every order charged (Dhan + statutory) with slippage.
- **VRP signal:** `VRP = iv30 − GARCH h21`; signal on session *t* uses the z-score known at *t−1*; walk-forward over a
  grid with a 45-session embargo; baselines "enter whenever possible" and "enter on random days".
- GARCH refits that do not converge reuse the previous parameters (`a99eca7`).

## 4. What was built / changed

| File | What it does |
|---|---|
| `tradingagents/analytics/volatility_model.py` | GARCH/GJR/EGARCH forecasts, baselines, QLIKE comparison |
| `tradingagents/analytics/implied_vol.py` | ATM IV and 30-day constant-maturity IV from closes |
| `scripts/quant_vol_forecasts.py` | All symbols in parallel; pooled comparison against both baselines and, for NIFTY, India VIX |
| `tradingagents/analytics/condor.py` | End-of-day short iron condor simulator; daily mark-to-market sums to each trade's return on max risk |
| `tradingagents/analytics/vrp.py` | VRP series, z-score signal, walk-forward with baselines |
| `tradingagents/analytics/costs.py` | `fill_charges` — charges for a single order (multi-leg trades) |
| `scripts/quant_vrp_condor.py` | Runner for the condor exit check |

## 5. Tests

- Volatility: realised vol looks only forward from the next session; QLIKE is zero for a perfect forecast and
  punishes under-forecasting more; **the GARCH forecast at *t* is unchanged by later data**; baselines are causal;
  GARCH tracks a known true volatility better than a rolling window.
- IV: forward and ATM IV recovered from synthetic closes; total-variance interpolation; untraded and expiry-day
  contracts skipped.
- Condor: strikes by delta, wings by width; a quiet market takes profit and a crash stops out; expiry settles at
  intrinsic; costs and slippage reduce the result; only monthly expiries traded, no trade when the signal is off.
- VRP: signal on *t* uses the z-score from *t−1*; VRP on common dates; walk-forward runs end to end with baselines.

## 6. Results

- **Exit check 1 passed:** GARCH beat historical vol out of sample on **31/31 symbols** (29 stocks + 2 indices).
  Pooled QLIKE figures for this run: not recorded in the PR (a later comparison at 10 sessions gave GARCH 0.336 vs
  EWMA 0.370 — [PA-20](PA_20-chronos-pretrained-model.md)).
- **Exit check 2 — VRP condor rejected on both indices** (run after the full store build; recorded in `554807d`,
  PR #9). 2021-04 → 2026-05 out of sample, 18 settings, costs + slippage:

| Index | Trades | Out-of-sample result | Beats random |
|---|---|---|---|
| NIFTY | 19 | Sharpe 0.04 (in-sample 1.29) | 64% |
| BANKNIFTY | 15 | +7.45% of risk per trade, Sharpe 0.30 | 94% |

  **Why:** a monthly condor allows at most 12 trades a year and the VRP filter keeps about 3–4, so five years give
  15–19 trades — the 100-trade gate cannot be met. BANKNIFTY hint: trades in choppy regimes averaged +49% of risk,
  calm −1.8% (too few to trust).

## 7. Verification

Run on the real NSE store (NIFTY, BANKNIFTY; 31 symbols for GARCH). Before the condor verdict, its accounting was
corrected: lot sizes made exact and spread close cost capped at the spread width
([PA-09](PA_09-agent-quant-tool-and-lightgbm.md)); returns stated on capital at 2% risk per trade and parameter
stability computed ([PA-10](PA_10-relative-strength-model.md), `7e7b979`).

## 8. Risks and open items

- GARCH is **in use** as a risk input (expected move, [PA-11](PA_11-ship-expected-move-and-daily-refresh.md)), not as
  a trading signal.
- End-of-day closes are not simultaneous fills; a wing and a short leg may be marked at different times.
- Open decision handed to the user at the time: how to get more condor trades (pool indices, add stock options,
  weekly entries, weekly expiries). Followed up in [PA-14](PA_14-retest-pooled-condor-and-relative-buffer.md); the
  pooled version later failed the backward holdout ([PA-17](PA_17-backward-holdout-2015.md)).
- Research and decision support only; not investment advice.

## Folded-in changes (option backtester accuracy)

These small records were merged here on 2026-10-26; the full text is in git history.

- **PA-07 — exit fixes (2026-10-23, PR #6).** The options engine taken from optopsy could report trades a trader never
  had and overstate profit:
  - take-profit / stop-loss scans ran past a planned early exit (`exit_dte`);
  - commission never reached realized P&L;
  - untraded expiry-day contracts were dropped.

  Fixed in `option_backtester/exits.py`, `simulator.py` and the NSE adapter: the scan stops at the planned exit,
  commission × quantity is deducted, and every expiry-day contract settles at intrinsic against the underlying close,
  as NSE settles it. Covered by regression tests in `tests/test_option_backtester_fixes.py`.
- **PA-28 — modelled bid / ask (2026-10-24).** The NSE adapter set `bid = ask = close`, so the backtester's slippage
  modes cost nothing. Quotes are now built around each close with the quant layer's cost model
  (`costs.DEFAULT_SLIPPAGE`: 1 tick + 1% per side, rounded outward to ₹0.05). That is about 1.2× the measured
  half-spread on liquid strikes: slightly pessimistic, the safe side. `half_spread=None` restores the old quotes for
  comparison. Backtests run before this were optimistic on option costs; none was used for a trading decision.
