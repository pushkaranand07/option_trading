# Strategy spec — Results-day iron butterfly, only when options look overpriced

> Stage 0 of [PROOF_PLAN.md](../PROOF_PLAN.md). Frozen 2026-10-24 **before any backtest of it was run**.
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
