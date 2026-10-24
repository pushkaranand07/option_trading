# Strategy spec: pooled VRP iron condor (NIFTY + BANKNIFTY)

> Stage 0 of [PROOF_PLAN.md](../plans/PROOF_PLAN.md). Frozen 2026-10-23. **Any change to anything below is a new
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
Max loss per condor = (widest wing − credit) × lot. Up to 8 condors can be open at once (2 indices × 4 books), so
**each condor ≤ 0.375% of capital** (8 × 0.375% = the 3% open-risk cap). Stage 5 may raise the cap only as the plan allows.

## Backtest evidence (Stage 1, 2021-04 → 2026-05, out of sample)
84 trades, 87% wins, +12.7% of max risk per trade, OOS Sharpe 0.65 (in-sample 1.04), beats random entry days in
100% of runs, profitable in all three regimes. **Missed:** trade count (84 < 100), deflated Sharpe (0.934 < 0.95),
positive folds (60% < 70%), parameter stability (0.41 < 0.5).

## Known risks
- **Parameter instability:** the walk-forward's choice moved between folds (e.g. NIFTY's last fold chose 2% wings and
  z 0.5). The frozen setting is the modal one; forward results may differ from the backtest more than usual.
- **Rare signal:** ~17 trades a year → Stage 3 needs ~21 months to reach the plan's 30 forward trades.
- **Tail events:** a gap through a wing loses the full defined risk; the stop fills a session late by design.
- **Data:** settlement uses the index close from NSE's official index file; if missing, the last earlier close.

## Stage 2 stress tests (2026-10-23, `scripts/quant_stress.py`): PASS
| Test | Result |
|---|---|
| Costs ×2 (charges + slippage) | +9.71% of risk per trade (base +11.05%) |
| Slippage ×3 on every leg | +9.62% |
| Start 1 / 2 / 3 months later | +10.96% / +10.82% / +10.33% |
| Block bootstrap, 95% interval of the mean | [+6.67%, +15.17%] |
| Trade-order Monte Carlo, 95th-pct drawdown | 1.54 × one condor's max risk = 0.58% of capital at 0.375% |
| Adani (Jan–Feb 2023) / election day (Jun 2024) | 1 / 7 condors open, no losses |
| COVID 2020 (crash proxy: GARCH trained on 1 year so the signal exists) | in the crash window 1 condor, −33% (stopped); **then two max losses (−96%, −101%) in the May–June 2020 rebound**; all 7 condors Jun-2019→Jun-2020 sum to −1.73 × max risk (≈ −0.65% of capital) |

**Known weakness found:** a sharp V-shaped rebound while IV is still elevated — the signal says "sell premium" just as
the market rips through the call wing. Within the risk limits, but a loss. Watch for it in paper trading.

## Backward holdout (2026-10-23, `scripts/quant_holdout.py`): FAIL
The frozen rules, unchanged, on entries 2015-08 → 2021-04 — years the settings' selection never saw:

| | NIFTY | BANKNIFTY | Pooled |
|---|---|---|---|
| Trades | 35 | 60 | 95 |
| Mean return on risk | +1.09% | −9.45% | **−5.57%** |
| Wins | 74% | 67% | 69% |

Bootstrap 95% interval of the mean [−16.1%, +5.5%]; beats random entry days in **60%** of 200 runs (needs 95%);
entering whenever possible −5.0%. All 190 frozen-rule trades (holdout + 2021–26): mean +2.7%, 95% interval
[−4.3%, +8.7%] — includes 0.

**Conclusion:** on unseen years the VRP filter did no better than random timing. The 2021–26 result did not carry over.

## Status
**REJECTED (2026-10-23)** — the backward holdout failed. Paper trading continues as **observation only** (the user's
choice): tracked for information, never reported as passing, not eligible for live trading on this evidence.
