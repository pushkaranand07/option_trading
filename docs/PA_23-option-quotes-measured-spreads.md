# PA-23 — Option trading costs measured from NSE's bid/ask, every evening

| | |
|---|---|
| **Status** | Done (merged) — capturing nightly since 2026-10-23 |
| **Scope** | `tradingagents/analytics/quotes.py`, `scripts/quant_option_quotes.py`, `scripts/quant_daily_update.py` (step `quotes`), `tests/test_quant_quotes.py` |
| **Related** | [PA-21](PA_21-results-day-iron-butterfly.md), [PA-22](PA_22-results-fly-overpriced-retest.md), [features/option-quotes](features/option-quotes.md), [architecture/11](architecture/11-nse-data-store.md) |
| **Pull request** | #25 (branch `quant/option-quotes`) |
| **Date** | 2026-10-24 |

## 1. Problem

Every option backtest assumed slippage of 1 tick + 1% of premium per leg per fill, because NSE's bhavcopy has closes
but no quotes. The results-day fly flips from −6.5% to break-even at half that assumption — so an assumption, not a
measurement, decided the verdict.

## 2. Findings

- NSE's option-chain API (`/api/option-chain-contract-info` for expiries, `/api/option-chain-v3` per expiry; `type`
  `Equity` or `Indices`) shows the best bid and offer per strike; after the close it holds the closing book (timestamp
  15:40).
- First snapshot (23-Oct-2026), November expiry, the legs a results fly would trade, 29 stocks:

| | ATM legs (sold) | Wings (bought) |
|---|---|---|
| Median premium | ₹35.96 | ₹9.62 |
| Real half-spread | ₹0.35 (1.08% of premium) | ₹0.15 (1.56%) |
| Model slippage | ₹0.41 | ₹0.15 |
| **Real ÷ model** | **0.84** | **0.88** |

Whole fly: **0.85×** the model at the median (middle half 0.71–1.23×). Worst: SUNPHARMA 4.76×, JSWSTEEL 4.11×,
DIVISLAB 3.11×, HINDALCO 2.59×, M&M 1.38×. The model is about right (slightly harsh); the fly needs 0.5×, so its
rejection stands.

## 3. Decisions

- Measure every evening instead of once: spreads on results eves and by strike only show up over time.
- Raw JSON kept exactly as served, dated by **NSE's own timestamp** — a weekend or holiday run gets the last session's
  book and writes nothing new.
- The capture is the **last** step of the 19:30 job: a failed step stops the rest, and an NSE hiccup must never block
  paper trading. One symbol failing does not lose the others.

## 4. What was built

| Piece | Does |
|---|---|
| `quotes.capture(symbols, client, root, expiries=3)` | saves `<raw>/option_quotes/<snapshot date>/<symbol>_<expiry>.json`; counts saved / already / failed |
| `quotes.parse`, `quotes.load` | one row per strike and type with bid, ask, quantities, IV, volume, OI, mid, half-spread |
| `quotes.versus_model` | median real half-spread ÷ model slippage per day and symbol, strikes within 10% of the underlying |
| `scripts/quant_option_quotes.py` | capture + report (`--report` to skip the capture) |

## 5. Tests

Capture dated by NSE's timestamp and not repeated; index chains requested as `Indices`; one failing symbol keeps the
rest; strikes without a bid dropped; mid, half-spread and real-vs-model arithmetic.

## 6. Results

First capture: 93 chains (31 symbols × 3 expiries). Across all strikes within 10% and all three expiries the median is
1.22× the model — wider than the fly legs because it includes the far month and very-near-expiry strikes, thin after
the close.

## 7. Verification

Real capture on 2026-10-24 (the Friday book); unit suite 1,349 passed; ruff clean.

## 8. Risks and open items

- Closing-book quotes can differ from intraday quotes; results-eve spreads not yet measured (needs captures on those dates).
- Not yet wired into backtests as the slippage source — that needs enough days to be a measurement, and would be
  declared before use.
