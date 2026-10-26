# PA-04 — Walk-forward evaluation harness and baselines (quant Phase 2)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/evaluate.py`, `tradingagents/analytics/costs.py`, `tradingagents/analytics/prices.py`, `tradingagents/dataflows/vendors/yahoo/market.py`, `scripts/quant_evaluate.py`, `scripts/quant_build_store.py`, `tests/test_quant_evaluate.py`, `tests/test_quant_costs.py` |
| **Related** | [PA-03](PA_03-quant-foundation-nse-data-store.md) · [PA-05](PA_05-garch-volatility-and-vrp-condor.md) · [PA-06](PA_06-regime-detection-hmm.md) (regime gate) · [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) (ledger cost fix) · [architecture/12-evaluation-and-validation.md](architecture/12-evaluation-and-validation.md) · [architecture/14-option-strategy-simulators-and-costs.md](architecture/14-option-strategy-simulators-and-costs.md) · [plans/QUANT_SIGNAL_LAYER_PLAN.md](plans/QUANT_SIGNAL_LAYER_PLAN.md) |
| **Pull request** | #3 (branch `quant/phase-2-harness`); commit `d4609fd` |
| **Date** | 2026-10-23 |

---

## 1. Problem

Every signal needs to be judged the same way, with costs, against baselines it must beat — otherwise each test
invents its own rules and a lucky result looks like skill.

## 2. Root cause / findings

- `prices.py` fetched Yahoo directly, bypassing the data layer, and defaulted to today — so a live, unfinished
  session could be stored as a finished bar.
- The cost model's brokerage was a generic "highest broker" default; the user trades on Dhan.

## 3. Decisions

- **No peeking:** the position for session *t* may use rows strictly before *t*. Checked by scrambling row *t* (does
  the position at *t* move?) and by truncation.
- **Execution at the next open:** a position for session *t* is entered at *t*'s open and earns open(t) → open(t+1) —
  when a manual trader can act on after-close data.
- **Costs on every position change**, at a position size the caller passes. Size is never assumed (the user sets it).
- **Baselines:** buy-and-hold, a 50/200 moving-average trend rule, and the same trades at random dates; a strategy
  must beat 95% of 1,000 random runs.
- **Dhan as the default broker** (the user's broker, from `https://dhan.co/pricing/`): ₹0 delivery brokerage, lower of
  ₹20 or 0.03% intraday, ₹20 per F&O order, DP charge ₹12.50 per scrip on a delivery sell (+ GST).
- **Layering rule:** `prices.py` goes through the data layer (`get_daily_history` in the Yahoo vendor) and stops at
  yesterday by default.

## 4. What was built / changed

| File | Change |
|---|---|
| `tradingagents/analytics/evaluate.py` (new, 385 lines) | One harness: walk-forward, trade ledger, per-year and per-regime breakdowns, gates, trial log; `same_bar_leaks`; equal capital per symbol |
| `scripts/quant_evaluate.py` (new) | Run a signal at one or more position sizes |
| `tradingagents/analytics/costs.py` | Dhan brokerage and DP charge defaults |
| `tradingagents/analytics/prices.py` | Fetch through the data layer; default end = yesterday |
| `tradingagents/dataflows/vendors/yahoo/market.py` | `get_daily_history()` — unadjusted OHLCV plus Adj Close, dividends, splits |

## 5. Tests

`tests/test_quant_evaluate.py`: session return runs open to next open; costs charged on position changes only; the
leak check passes honest signals and catches peeking; neighbours are one step away in one parameter; **a random
strategy is never approved**; **a planted edge is found**; opens use the dividend-adjusted basis.
`tests/test_quant_costs.py` updated for the Dhan defaults.

## 6. Results

- **Phase 2 exit gate passed** (PR body, tracker): a random signal is rejected on synthetic and real data; a planted
  AR(1) edge (each day's return partly repeating the previous day's) is found.
- **First real result:** the 50/200 MA trend rule was rejected — it beat random timing only 6% of the time
  (tracker results table).

## 7. Verification

Run on real data for the MA-trend result above (tracker, Phase 2: "First real results recorded").

## 8. Risks and open items

- Ledger costs on resizes and flips did not match the daily series; fixed after an independent review in
  [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) (`088d6b6`).
- Stopping at yesterday was later relaxed to include today's bar from 16:00 (tracker bug list; record not in this PR).
- The MA trend rule was later dropped at the user's request (tracker, Phase 6 "On hold").
- Research and decision support only; not investment advice.
