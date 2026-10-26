# PA-18 — Results fly: cost diagnosis and the "only overpriced events" re-test (rejected)

| | |
|---|---|
| **Status** | Done (merged) — re-test **rejected**; no more variants of this idea on the same data |
| **Scope** | `tradingagents/analytics/events.py` (`overpriced`, implied move), `scripts/quant_results_fly.py --overpriced`, [strategies/results_iron_fly_overpriced.md](strategies/results_iron_fly_overpriced.md) |
| **Related** | [PA-17](PA_17-results-day-iron-butterfly.md), [PA-19](PA_19-option-quotes-measured-spreads.md) |
| **Pull request** | #24 (branch `quant/results-fly-overpriced`) |
| **Date** | 2026-10-24 |

## 1. Problem

The user asked how to fix the rejected results-day fly (user). Only causes that can be fixed honestly are re-tested,
with the change declared in advance and counted as a new trial.

## 2. Root cause — cost diagnosis (measurement only, not a trial)

The same 984 trades re-priced:

| Same trades | Mean per trade (% of max risk) | Wins |
|---|---|---|
| No costs at all | **+5.51%** | 65% |
| Charges, no slippage | +3.51% | 62% |
| Half the slippage assumption | **+0.20%** (break-even) | 57% |
| Full assumption | −6.46% | 49% |

**Friction is the whole problem**; the trade breaks even at half the assumed slippage. Slippage splits 72% on the ATM
legs and 28% on the wings; the wings' exit fills are 14% of all slippage (~1 point of max risk).

## 3. Decisions

| Option | Decision |
|---|---|
| Trade only when options look overpriced | **Tested** (new spec, frozen first) |
| Let the wings expire (fewer fills) | **Rejected**: saves ~1 point, and stock options are physically settled — the proof plan's risk rule 5 requires exiting before expiry day |
| Lower the slippage assumption | **Rejected**: that would be fitting the result; measure it instead ([PA-19](PA_19-option-quotes-measured-spreads.md)) |
| Other wing widths / holds until something passes | **Rejected**: tuning on the result |

Filter (frozen in [the spec](strategies/results_iron_fly_overpriced.md)): implied move = ATM straddle / parity forward
on the entry day; historical move = median |close at exit / close at entry − 1| over the stock's previous 8 results
windows that ended before this entry (≥ 4 required); trade only if implied ≥ **1.25×** historical. Judged at the
**full** slippage assumption with unchanged pass marks.

## 4. What was built

`FlyTrade.implied_move` (from the entry closes), `events.overpriced(trades, windows, closes)`, `--overpriced` flag.

## 5. Tests

A planted 50% move **after** a trade's entry is never seen by the filter; 1.25× is applied exactly (4.9% rejected,
5.1% kept on a 4% history); fewer than 4 earlier windows → no trade.

## 6. Results

745 of the 984 trades passed the filter: mean **−4.71%** of max risk (CI [−7.37%, −2.01%]), 1 of 9 years positive
(2021), beats random quiet days 100%, deflated Sharpe 0.000 → **rejected**. The filter added ~1.7 points: options almost
always price more than the *median* results-day move, so it removes little.

## 7. Verification

Full run on 29 stocks; trial logged (N = 184); unit suite 1,346 passed; ruff clean.

## 8. Risks and open items

The one open question is real execution cost. Measured spreads ([PA-19](PA_19-option-quotes-measured-spreads.md))
came out at 0.85× the model, so the rejection stands unless the user's own fills are near the mid-price.
