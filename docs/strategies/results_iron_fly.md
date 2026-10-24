# Strategy spec — Results-day iron butterfly (IV crush) on stock options

> Stage 0 of [PROOF_PLAN.md](../PROOF_PLAN.md). Frozen 2026-10-24 **before any backtest of it was run**.
> Any change to these rules is a new strategy and a new trial. Research only — not investment advice.

## Idea
Implied volatility of a stock's options rises into its quarterly results and collapses once they are out. A short
at-the-money straddle held across the results date collects that collapse, but loses when the stock moves more than
the options priced in. Wings make the risk defined (proof plan, risk limit 1: no naked short options).

## Universe and data
- The 29 F&O stocks (`universe.py`), stock options from the NSE F&O bhavcopy store, 2018-01 → today.
- Results dates: NSE board meetings (`/api/corporate-board-meetings`) whose purpose, or the intimation's description,
  says "financial result"; one event per (stock, date).
- **Known in advance:** an event is used only if NSE received its intimation before the entry session (the intimation
  timestamp is in the data; normally weeks ahead).

## Rules
| Item | Rule |
|---|---|
| Event date *D* | the board-meeting date |
| Entry | close of the last session **before** *D* |
| Exit | close of the first session **after** *D* (covers results released during *D* or after its close, and weekend meetings) |
| Expiry | the nearest monthly expiry strictly after the exit session, with ≤ 45 calendar days at entry; otherwise no trade |
| Short legs | sell the ATM call and ATM put: the strike nearest the parity forward (`implied_vol.expiry_atm`); both must have traded on the entry day |
| Wings | buy the nearest listed put / call at least **1 × the ATM straddle's price** below / above the short strike |
| Prices | each leg's close; NSE settlement price if it did not trade (flagged); each spread's close cost capped at its width |
| Costs | Dhan ₹20/order + 2026 statutory charges (`costs.py`), slippage 1 tick + 1% of premium per leg per fill |
| Size (live only) | max loss = (wing width − credit) × lot; ≤ 0.5% of capital per trade at Stage 4 |

No parameter is fitted: there is nothing to tune, so no walk-forward is needed. The whole 2018–2026 sample is out of sample.

## Tests (all must pass)
| Test | Pass mark |
|---|---|
| Trades | ≥ 100 |
| Mean return on max risk | > 0, block-bootstrap 95% interval excludes 0 |
| vs random | same trade on the same stock on random non-event days (no results within ±5 sessions), same hold: event mean beats ≥ 95% of 200 random runs |
| Years | positive in ≥ 70% of calendar years |
| Deflated Sharpe | ≥ 0.95, counting every trial in the trial log |
| Stress (Stage 2, only if the above pass) | costs ×2 still positive; worst single trade ≤ max risk |

If it passes, it goes to Stage 3 (forward paper trading) like any other candidate; it is not traded on backtest evidence.

## Result (2026-10-24, `scripts/quant_results_fly.py`): REJECTED
984 trades on 1,009 results dates, 2018-01 → 2026-10 (29 stocks).

| Test | Result |
|---|---|
| Trades ≥ 100 | ✅ 984 |
| Mean > 0, bootstrap CI above 0 | ❌ mean **−6.46%** of max risk, CI [−9.06%, −3.76%]; wins 49% |
| Beats random quiet days ≥ 95% | ✅ 100% of 200 runs (random days −11.18%) |
| Positive years ≥ 70% | ❌ 0 of 9 (every year negative, 2026 worst at −16.4%) |
| Deflated Sharpe ≥ 0.95 | ❌ 0.000 (N = 183) |

**What it shows:** the IV crush is real (results days beat random days by ~4.7 points of max risk, every run), but it is
smaller than the cost of trading it. Charges are ~2% of max risk per trade; the rest of the loss is slippage across
eight option fills in two days and moves bigger than the straddle priced. A defined-risk 4-leg structure on stock
options cannot harvest it at retail cost. Not retested with other wings or holds: that would be tuning on the result.
