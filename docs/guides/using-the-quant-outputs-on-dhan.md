# Using the quant outputs when you trade on Dhan

> **Status:** Current.
> **Scope:** how to use the system's numbers in your own manual trading. Research and decision support only — not
> investment advice. The system never places orders.
> **Last verified against the code:** 2026-10-24

---

## 1. What is safe to use, and what is not

| Output | Use it for | Status |
|---|---|---|
| **Expected move** (GARCH, 5 / 10 / 21 sessions) | stop distance, option strike width, position size | ✅ validated as a **risk** input |
| **Market regime** (calm / choppy / stress) | how much risk to take; choppy and stress mean bigger moves | ✅ validated for **volatility**, not direction |
| Implied vol vs the GARCH forecast | whether options look expensive or cheap relative to forecast | context only |
| **Measured option spreads** | which stocks are too costly for multi-leg option trades | measured nightly |
| Any "signal" in the verdict list | — | ❌ **none has passed**; never trade on them |

## 2. Where to find the numbers

- **Agent report:** run an analysis ([running an analysis](running-an-analysis.md)); section "VI. Quant Context" has
  the regime, volatility forecasts, expected move and implied vol for that date.
- **Market Map:** open `reports/market_map/india-market-map.html` in a browser (rebuilt every weekday at 19:30).
- **Option spreads:** `.venv\Scripts\python.exe scripts\quant_option_quotes.py --report`.

## 3. Using the expected move

The expected move is one standard deviation: about 2 moves in 3 stay inside it.

- **Stops:** a stop inside one expected move is likely to be hit by noise. Example from the report for RELIANCE
  (2026-03-23): ±4.9% = ±Rs 69 over 10 sessions on a close of Rs 1,414.
- **Option strikes:** short strikes inside one expected move are touched often; wings about one expected move beyond
  the short strike match the risk the market is pricing.
- **Size:** risk per trade = (entry − stop) × quantity. Keep it to a fixed share of capital you choose; the proof plan
  caps it at 0.5% while a strategy is unproven ([proof plan §6](../plans/PROOF_PLAN.md)).

## 4. Using the regime

| Regime | Next-month NIFTY volatility (2021–26) | Practical meaning |
|---|---|---|
| Calm | 11.5% | smaller moves; premium sellers face less risk |
| Choppy | 15.1% | bigger moves; wider stops, smaller size |
| Stress | rare (~1–2% of days) | defined-risk only, smaller size |

The regime does **not** predict direction (returns by regime were not significantly different).

## 5. Costs before you trade

- Multi-leg stock-option trades (butterflies, condors) pay the spread on every leg: the results-day butterfly made
  +5.5% of risk before costs and lost −6.5% after them ([PA-17](../PA_17-results-day-iron-butterfly.md)).
- Measured closing spreads are about 1.1% of premium at the money and 1.6% on wings; some stocks are 3–5× worse
  (SUNPHARMA, JSWSTEEL, DIVISLAB on 23-Oct-2026). Prefer limit orders near the mid-price.

## 6. What to send back

Your real fills (screen price vs filled price), one contract note, and your tradebook make the system's cost model and
the trade journal real — see [exporting your Dhan tradebook](exporting-your-dhan-tradebook.md).
