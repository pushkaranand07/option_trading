# Strategy spec — Results-day iron butterfly, only when options look overpriced

> Stage 0 of [PROOF_PLAN.md](../plans/PROOF_PLAN.md). Frozen 2026-10-24 **before any backtest of it was run**.
> A re-test of [results_iron_fly.md](results_iron_fly.md) (rejected), changing one thing for a stated reason. It counts
> as a new trial. Research only — not investment advice.

## Why this change
The original lost −6.5% of max risk per trade at the full slippage assumption, yet made +5.5% before costs: the IV
crush is real but too small on average to pay the friction. Many results days move more than the straddle priced.
Selling only when the options price a move clearly larger than the stock's own history of results-day moves should
keep the trades where the crush is largest.

Considered and **not** adopted: leaving the wings to expire to save fills. It saves only ~14% of slippage (~1 point of
max risk) and stock options are physically settled; the proof plan's risk rule 5 requires exiting before expiry day.

## Rules
Everything in [results_iron_fly.md](results_iron_fly.md) (events, entry, exit, expiry, strikes, wings, prices, costs at
the **full** slippage assumption), plus one filter, decided at the entry close:

| Item | Rule |
|---|---|
| Implied move | (ATM call close + ATM put close) / parity forward, on the entry day |
| Historical move | median of \|close at exit / close at entry − 1\| over the stock's **previous** results windows (entry → exit, adjusted closes), the last 8 that ended before this entry; at least 4 required |
| Trade only if | implied move ≥ **1.25 ×** historical move |

## Tests (unchanged from the original)
≥ 100 trades · mean > 0 with block-bootstrap 95% interval above 0 · beats the same trade on random quiet days in ≥ 95%
of 200 runs · positive in ≥ 70% of years · deflated Sharpe ≥ 0.95 counting every logged trial (now including the
original). If it passes: Stage 2 stress (costs ×2), then Stage 3 forward paper trading with the user's real fills.

## Result (2026-10-24, `scripts/quant_results_fly.py --overpriced`): REJECTED
745 of the original 984 trades passed the filter (2018-10 → 2026-10).

| Test | Result |
|---|---|
| Trades ≥ 100 | ✅ 745 |
| Mean > 0, bootstrap CI above 0 | ❌ mean **−4.71%** of max risk (original −6.46%), CI [−7.37%, −2.01%]; wins 50% |
| Beats random quiet days ≥ 95% | ✅ 100% of 200 runs (random −11.19%) |
| Positive years ≥ 70% | ❌ 1 of 9 (2021 only) |
| Deflated Sharpe ≥ 0.95 | ❌ 0.000 (N = 184) |

**What it shows:** the filter helped by ~1.7 points but kept three quarters of the trades: options almost always price
more than the stock's *median* results-day move, so the median is a weak yardstick. The friction gap (~10 points of max
risk at the assumed slippage) is far larger than anything selection recovered. Two honest attempts, both rejected; no
further variants of this idea will be tried on the same data. The one open question is real execution cost: only the
user's actual Dhan fills can show whether slippage is well below the model's 1 tick + 1% per leg.
