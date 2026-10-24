# PA-28 — Option backtester: modelled bid/ask, so slippage counts

| | |
|---|---|
| **Status** | Done |
| **Scope** | `tradingagents/integrations/optopsy/adapter.py` (`cost_model_half_spread`, `quote_from_close`, `bhavcopy_to_optopsy(half_spread=...)`), `tests/test_optopsy_bridge_compliance.py`, `tests/test_option_backtester_fixes.py` |
| **Related** | [PA-07](PA_07-option-backtester-exit-fixes.md), [PA-23](PA_23-option-quotes-measured-spreads.md) (measured spreads), [architecture/08](architecture/08-option-backtester.md) |
| **Pull request** | branch `fix/backtester-bid-ask` |
| **Date** | 2026-10-24 |

## 1. Problem

Found while writing the docs: the NSE adapter set `bid = ask = close`. optopsy's slippage modes (`spread`,
`liquidity`, `per_leg`) scale the bid-ask half-spread, which was zero — so every option fill in the backtester was free
of spread costs, and the `slippage` setting changed nothing. Only `commission` added costs.

## 2. Decision

Build bid / ask around each close with the **same cost model the quant layer uses** (`costs.DEFAULT_SLIPPAGE`: 1 tick +
1% of price per side), rounded outward to the ₹0.05 tick. Measured NSE closing quotes put that model at ~1.2× the real
half-spread on liquid strikes (real ÷ model 0.85, [PA-23](PA_23-option-quotes-measured-spreads.md)) — slightly
pessimistic, which is the safe side for a backtest. Expiry day stays at intrinsic (NSE settles at one price).
`half_spread` is a parameter; `None` gives the old chain for comparison.

## 3. Tests

- A real NIFTY row (close 226.4): bid 224.05, ask 228.75; `half_spread=None` keeps `bid == ask`.
- One call bought at close 10 and sold at close 12: with the old flat quotes `spread` and `mid` give the same P&L;
  with modelled quotes `mid` gives 2.00 × 75 and `spread` 1.65 × 75 (ask 10.15, bid 11.80).
- Expiry-day intrinsic valuation unchanged. 22 adapter and backtester tests pass.

## 4. Risks and open items

- A modelled spread, not a real one: illiquid stocks can be 3–5× wider (SUNPHARMA, JSWSTEEL, DIVISLAB on
  2026-10-23). Once enough nightly quotes exist, a per-symbol measured spread can replace the model (declared first).
- Backtests run before this change were optimistic on option costs; none is used for a trading decision.
