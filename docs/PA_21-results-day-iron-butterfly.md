# PA-21 — Results-day iron butterfly (IV crush) on stock options: rejected

| | |
|---|---|
| **Status** | Done (merged) — strategy **rejected** |
| **Scope** | `tradingagents/analytics/events.py`, `scripts/quant_results_fly.py`, `tests/test_quant_events.py`, [strategies/results_iron_fly.md](strategies/results_iron_fly.md) |
| **Related** | [PA-22](PA_22-results-fly-overpriced-retest.md) (re-test), [PA-23](PA_23-option-quotes-measured-spreads.md) (measured spreads), [architecture/14](architecture/14-option-strategy-simulators-and-costs.md) |
| **Pull request** | #23 (branch `quant/results-iron-fly`) |
| **Date** | 2026-10-24 |

## 1. Problem

With every generic signal rejected, the user chose an **event-window** test (user): do options around scheduled events
behave predictably? Quarterly results give the most events (29 stocks × ~4 a year × 8 years ≈ 1,000), enough for the
100-trade gate; RBI and Budget days give only ~40.

## 2. Findings before the test

- NSE's board-meeting API (`/api/corporate-board-meetings`) returns every results date since 2018 in one request per
  stock, each with the intimation timestamp — proof the date was public before entry.
- The condor simulator exits only on take-profit, stop-loss or expiry; an event trade needs a fixed exit, so a new
  module reuses its pricing pieces (marks, fills, charges, spread-width cap).

## 3. Decisions

- **Spec frozen and pushed before any backtest** ([strategies/results_iron_fly.md](strategies/results_iron_fly.md),
  first commit of the branch):
  - entry: close of the last session **before** the meeting; exit: close of the first session **after** it (covers
    results released during the day, after the close, or at a weekend meeting);
  - nearest monthly expiry strictly after the exit, ≤ 45 days; short ATM call + put (strike nearest the parity forward,
    both traded that day); wings one ATM-straddle price away; Dhan + statutory charges; slippage 1 tick + 1% per leg per fill;
  - an event counts only if NSE received the intimation before the entry session.
- Pass marks: ≥ 100 trades; mean > 0 with block-bootstrap 95% interval above 0; beats the same trade on random quiet
  days (no results within ±5 sessions, same stock, year and hold) in ≥ 95% of 200 runs; ≥ 70% of years positive;
  deflated Sharpe ≥ 0.95 counting every logged trial (183). No parameter is fitted, so no walk-forward.
- Deflated Sharpe uses the no-skill variance of an estimated Sharpe, 1/(n − 1), because there is no parameter grid.

## 4. What was built

| Function | Does |
|---|---|
| `fetch_board_meetings`, `results_events` | download (cached as raw JSON), keep results meetings, one event per date with the earliest intimation |
| `event_windows` | (event, entry, exit) sessions; drops events announced too late |
| `build_fly`, `window_trade` | strikes and entry marks; prices the exit; charges and slippage; spread-width cap |
| `quiet_entries` | sessions with no results within a buffer, for the random baseline |

## 5. Tests

Synthetic Black-76 option chain: an IV collapse pays; a 30% jump loses the defined risk plus exit slippage on the far
side; no trade when the only expiry falls inside the window; a meeting announced the evening before entry is skipped;
results dates deduplicated with the earliest intimation; quiet-day selection.

## 6. Results

984 trades on 1,009 results dates (2018-01 → 2026-10):

| Test | Result |
|---|---|
| Trades ≥ 100 | ✅ 984 |
| Mean > 0, CI above 0 | ❌ **−6.46%** of max risk, CI [−9.06%, −3.76%]; wins 49% |
| Beats random quiet days | ✅ 100% of 200 runs (random −11.18%) |
| Positive years | ❌ 0 of 9 (2026 worst, −16.4%) |
| Deflated Sharpe | ❌ 0.000 |

**The IV crush is real** — results days beat random days every time, by ~4.7 points of max risk — but it is **smaller
than the friction** of eight option fills in two days.

## 7. Verification

Two-stock smoke run (INFY, TCS) before the full run; trades CSV in `<store>/events/`; trial logged; unit suite 1,345
passed; ruff clean.

## 8. Risks and open items

- The verdict depends on the slippage assumption — diagnosed in [PA-22](PA_22-results-fly-overpriced-retest.md) and
  measured in [PA-23](PA_23-option-quotes-measured-spreads.md).
- For trading on Dhan: selling butterflies or straddles on stock options into results is right about the market but
  loses to costs.
