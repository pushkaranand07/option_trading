# Option strategy simulators and costs

> **Status:** Current.
> **Scope:** `tradingagents/analytics/costs.py`, `condor.py`, `vrp.py`, `quiet_condor.py`, `events.py`, `sizing.py`;
> `scripts/quant_vrp_condor.py`, `scripts/quant_quiet_condor.py`, `scripts/quant_results_fly.py`.
> **Last verified against the code:** 2026-10-24

Research only, not investment advice. Every strategy described here was **rejected**; the simulators remain as the
tools any new candidate will be judged with.

---

## 1. Costs — `costs.py`

Rates as of 2026-10-23 are applied to **all** history on purpose: older trades were cheaper (F&O STT rose on
2026-04-01), so a strategy that only pays at old rates is rejected rather than flattered. Sources are cited in the
module docstring (NSE circulars FATAX/73524 and FA/73061, broker charge pages, Dhan's pricing page). Budgets change
these rates; re-check before relying on them.

`ChargeRates` (defaults):

| Charge | Delivery | Intraday | Futures | Options |
|---|---|---|---|---|
| STT (buy / sell, on turnover; options on premium) | 0.1% / 0.1% | 0 / 0.025% | 0 / 0.05% | 0 / 0.15% |
| STT on exercise (buyer, on intrinsic value at ITM expiry) | — | — | — | 0.15% |
| NSE transaction charge incl. IPFT (each side) | ₹307 / crore | ₹307 / crore | ₹183 / crore | ₹3,553 / crore |
| SEBI fee (each side) | ₹10 / crore | ₹10 / crore | ₹10 / crore | ₹10 / crore |
| Stamp duty (buy side) | 0.015% | 0.003% | 0.002% | 0.003% |
| Dhan brokerage per order | ₹0 | lower of ₹20 or 0.03% | ₹20 | ₹20 |
| DP charge (delivery sell, per scrip) | ₹12.50 | — | — | — |
| GST | 18% on brokerage + exchange + SEBI fee + DP charge |||

`Slippage` (not a charge, but paid on every fill): equity / futures 5 basis points (0.05%) of price per fill; options
**1 tick (₹0.05) + 1% of premium** per leg per fill. Measured closing spreads were 0.85× this model on the first
snapshot ([11](11-nse-data-store.md), section 6).

Functions: `round_trip` (a full `Breakdown`: brokerage, STT, exchange, SEBI, stamp, DP, GST, slippage; `charges`
excludes slippage as a contract note does), `fill_charges` (one order, for multi-leg option trades), `cost_fraction`
(round trip as a fraction of position value, for return-based backtests).

**Open item:** the cost model has not yet been matched to a real Dhan contract note within ₹1 (it needs one from the
user; tracker, Phase 1).

## 2. Iron condor simulator — `condor.py`

An iron condor sells a put spread and a call spread together; the bought wings cap the loss. Rules agreed with the
user (2026-10-23), defaults in `CondorParams`:

| Rule | Default |
|---|---|
| Expiry | nearest **monthly** (last listed expiry of a calendar month) with 20–45 calendar days left |
| One condor at a time | per underlying (per book, with staggered books) |
| Entry | on a session whose signal is on (signal already lagged); fill at that session's close less slippage |
| Short strikes | out-of-the-money put and call whose Black-76 delta (own IV, parity forward) is nearest `short_delta = 0.20` |
| Wings | nearest listed strikes at least `wing_pct = 3%` of the forward further out |
| Take profit / stop | P&L ≥ 50% of credit / loss ≥ 2× credit, checked on the close, **filled at the next session's close** |
| Expiry settlement | intrinsic value against the index close; ITM long legs pay exercise STT |
| Costs | `fill_charges` on every order (8 per round trip) plus slippage |

- **Marks.** Each leg is marked at its close, or NSE's settlement price when it did not trade; an untraded wing at entry
  is flagged.
- **Spread-width cap.** End-of-day marks are not simultaneous, so a spread can appear to cost more than its width.
  `close_cost` caps each spread at its width and flags it.
- **Missing expiry close.** Settles on the last earlier index close, never the entry prices.
- **Results** are rupees per lot and `return_on_risk` (P&L ÷ (widest wing − credit) × lot), so lot-size changes do not
  distort them. The daily mark-to-market series is a fraction of max risk.
- **Speed.** Prepared chains are cached per chain object; the tracker records repeated runs as 100× faster with
  identical results.
- **Staggered books.** `simulate_staggered(books=4)`: book *j* may enter only in ISO weeks with `week % 4 == j`, each
  book holds at most one condor and gets ¼ of the capital. `offset` shifts the week assignment (a timing stress test).
- `include_open=True` also returns the condor still open at the end (paper trading needs it).

## 3. VRP signal and walk-forward — `vrp.py`

Volatility risk premium: `VRP = iv30 − GARCH 21-session forecast`. The z-score over the previous 252 sessions (at least
126), as of *t−1*, must exceed `z` to allow an entry on *t*.

`evaluate_condor` simulates every grid point once over all history, then per fold picks the best training Sharpe and
keeps the trades entered in its test window. Defaults: train 756, test 126, **embargo 45** sessions (longer than any
condor). Baselines on the same out-of-sample days and rules: "enter whenever possible" and random entry days at the
signal's own entry rate. `risk_fraction = 0.02` scales the series onto capital before the gates compound it. `pool()`
combines several underlyings with capital split equally. `load_inputs(symbol)` reads chain, spot (NSE index close, else
the future's close), lots and VRP from the store. `scripts/quant_vrp_condor.py` runs an 18-point grid (short delta ×
wing width × z), all logged.

Results ([../strategies/vrp_condor_pooled.md](../strategies/vrp_condor_pooled.md), tracker):

- Single condor per index: rejected (15–19 trades in 5 years; the 100-trade gate cannot be met).
- 4 staggered books, NIFTY + BANKNIFTY pooled, 2021-04 → 2026-05: 84 trades, +12.7% of max risk per trade, beats random
  100%, but missed trade count, deflated Sharpe (0.934), positive folds (60%) and parameter stability (0.41).
- Frozen as a Stage 0 spec (NIFTY: delta 0.25, wings 4%, z 1.5; BANKNIFTY: delta 0.15, wings 4%, z 0.5), passed
  Stage 2, then **failed the backward holdout** (2015–21: −5.57% per trade, beats random 60%) → rejected.

## 4. Quiet-stock condor — `quiet_condor.py`

Every 10 sessions, rank the 29 stocks by GARCH 10-session forecast ÷ trailing 60-session vol and open a monthly condor
(delta 0.20, 4% wings, 50% / 2× exits) on the 5 lowest, each with ⅕ of capital. Settles on NSE's near-month futures
close. Baselines: 5 random stocks (many runs) and all stocks; robustness at delta 0.15 and 0.25. One trial, no
walk-forward (GARCH is not fitted to the question), so the OOS/IS gate cannot be evaluated.

Result (2026-10-23): GARCH's picks lose less than random (beats random 92%), but selling stock condors loses money:
Sharpe −0.44 (random −0.84, all stocks −1.22) → **rejected**.

## 5. Results-day iron butterfly — `events.py`

Spec: [../strategies/results_iron_fly.md](../strategies/results_iron_fly.md). An iron butterfly sells the at-the-money
call and put and buys wings either side.

- **Events.** NSE board meetings (`/api/corporate-board-meetings`, cached as raw JSON under `raw/board_meetings/`) whose
  purpose or description mentions financial results. An event is used only if NSE received its intimation **before**
  the entry session.
- **Trade.** Sell the ATM straddle at the close of the last session before the meeting date, buy wings at least
  `wing_mult = 1.0` × the straddle price away, close everything at the close of the first session after it. Expiry: the
  nearest monthly after the exit, ≤ 45 days at entry. Same marks, fills, charges and spread-width cap as `condor.py`.
- **Random baseline.** The same trade on random quiet days (`quiet_entries`: no results within ±5 sessions).
- **Overpriced filter** (`overpriced`, spec
  [../strategies/results_iron_fly_overpriced.md](../strategies/results_iron_fly_overpriced.md)): trade only when the
  implied move (straddle ÷ forward) is at least 1.25 × the median absolute move of the stock's previous 8 results
  windows (at least 4).

Results (2026-10-24): 984 trades, mean −6.46% of max risk (bootstrap CI [−9.06%, −3.76%]), every year negative →
**rejected**; results days beat random days in 100% of runs, so the IV crush is real but smaller than the friction.
Cost diagnosis: +5.5% per trade before costs, break-even at half the assumed slippage. Overpriced re-test: 745 trades,
−4.71% → **rejected**. No further variants on the same data.

## 6. Position sizing — `sizing.py`

`Kelly f* = p − (1 − p) / b` (p = win probability, b = average win ÷ average loss). `size()` returns ¼ of Kelly
(`kelly_fraction = 0.25`), capped at `max_risk = 1%` of capital at risk; no edge (f* ≤ 0) means no trade. The capital
is an argument — nothing stores or assumes it. `quantity(risk_rupees, entry, stop, lot)` rounds down to whole lots.

The proof plan's stage caps sit below this: Stage 4 at 0.5% per trade and ≤ 3% total open risk (8 possible VRP
condors → 0.375% each). `sizing.py` is for use once a signal has a measured edge; none has yet.

Related: [12 — evaluation and validation](12-evaluation-and-validation.md),
[15 — daily refresh and paper trading](15-daily-refresh-and-paper-trading.md).
