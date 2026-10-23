# Strategy spec: pooled VRP iron condor (NIFTY + BANKNIFTY)

> Stage 0 of [PROOF_PLAN.md](../PROOF_PLAN.md). Frozen 2026-10-23. **Any change to anything below is a new
> strategy and starts again at Stage 1.** The git commit that adds this file is the strategy's identity.

## Idea
Options are usually priced above the volatility that follows (the volatility risk premium). Sell defined-risk
premium only when 30-day implied vol is unusually high relative to the GARCH forecast of realised vol.

## Instruments and timing
- NIFTY and BANKNIFTY **monthly** index options (the last listed expiry of each calendar month), 20–45 calendar
  days to expiry at entry. Cash-settled.
- Signal for session *t* uses only data published before *t* opens (files dated *t−1* and earlier).
- Fills at session *t*'s closing prices (end-of-day; you place orders near the close).

## Entry signal
- VRP = 30-day ATM implied vol (VIX-style: put-call-parity forward, Black-76, total-variance interpolation)
  − GARCH(1,1) forecast of the next 21 sessions' volatility.
- z = (VRP − its 252-session mean) / its 252-session standard deviation, as of *t−1*.
- **Enter when z > threshold.**
- **4 staggered books**: book *j* may enter only in ISO weeks with `week % 4 == j`; each book holds at most one
  condor; each book gets ¼ of the strategy's capital. Each index gets ½.

## Frozen parameters (the walk-forward's most frequent choice, 6 of 10 folds each)
| | short delta | wing width | z threshold |
|---|---|---|---|
| NIFTY | 0.25 | 4% of the forward | 1.5 |
| BANKNIFTY | 0.15 | 4% of the forward | 0.5 |

## Structure and exits
- Short put and short call at the out-of-the-money strikes nearest the target |delta| (Black-76 on the parity forward,
  each option's own IV); long wings at the nearest listed strikes at least the wing width further out.
- **Take profit** when the condor's P&L reaches 50% of the credit; **stop** when the loss reaches 2× the credit. Both
  are checked on the close and **filled at the next session's close**.
- Otherwise held to expiry and settled at intrinsic value against the index close (exercise STT on ITM long legs).
- Each spread's close cost is capped at its width (end-of-day marks are not simultaneous).

## Costs
Dhan brokerage ₹20 per order (8 orders per round trip), STT, NSE transaction charges, SEBI fee, stamp duty, GST at
2026 rates (`costs.py`); slippage 1 tick + 1% of premium per leg per fill.

## Sizing (live stages only)
Max loss per condor = (widest wing − credit) × lot. Stage 4: ≤ 0.5% of capital per condor; ≤ 3% total open risk.

## Backtest evidence (Stage 1, 2021-04 → 2026-05, out of sample)
84 trades, 87% wins, +12.7% of max risk per trade, OOS Sharpe 0.65 (in-sample 1.04), beats random entry days in
100% of runs, profitable in all three regimes. **Missed:** trade count (84 < 100), deflated Sharpe (0.934 < 0.95),
positive folds (60% < 70%), parameter stability (0.41 < 0.5).

## Known risks
- **Parameter instability:** the walk-forward's choice moved between folds (e.g. NIFTY's last fold chose 2% wings and
  z 0.5). The frozen setting is the modal one; forward results may differ from the backtest more than usual.
- **Rare signal:** ~15 trades a year → Stage 3 needs ~3 years to reach the evidence bar.
- **Tail events:** a gap through a wing loses the full defined risk; the stop fills a session late by design.
- **Data:** settlement uses the index close from NSE's official index file; if missing, the last earlier close.

## Status
Stage 1: narrowly not passed. Admitted to **Stage 3 (paper only)** to collect the missing trades on new data.
Not eligible for Stage 4 until Stage 3 passes.
