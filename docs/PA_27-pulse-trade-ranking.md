# PA-27 — Pulse trade ranking: concrete trades with strikes, entry, target and stop, best first

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/strategist.py` (`rank`, `_structures`, `_index_levels`; iron-butterfly check), `webapp/server.py` (`GET /api/rank/{symbol}`), `webapp/static/*` (ranked table in the AI strategist section), `tests/test_strategist.py` |
| **Related** | [PA-24](PA_24-trade-ticket-and-premium-levels.md), [PA-26](PA_26-evidence-score-and-ai-track-record.md), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/trade-ranking` |
| **Date** | 2026-10-26 |

## 1. Problem

The user's screenshot showed an AI iron condor refused with "an iron condor is buy put < sell put < sell call < buy
call", leaving no trade to act on. They asked for:

- a proper call: a strike (for example "22700 CE") with a proper stop loss and target;
- several such trades, ranked from highest to lowest.

The refusal itself was a bug. The AI sold the put and the call at the same strike (22,700, at max pain): an iron
butterfly. That is also limited-risk, but the check demanded the sold put strike be strictly below the sold call
strike.

## 2. Change

### Iron butterfly accepted

The iron-condor check now allows the sold put and the sold call at the same strike.

### Pulse trade ranking (`strategist.rank`)

The ranking is built from rules, with no LLM, in about 5 s:

- **Directions.** For both bullish and bearish, candidate structures come from the live chain's strikes:
  - single calls / puts at the money, 1 and 2 strikes out of the money;
  - debit spreads 2 and 4 strikes wide;
  - credit spreads 1–2 strikes out of the money, 2 strikes wide.
- **Index levels.** The entry zone is ±10% of a typical move to expiry around spot (the typical move is the GARCH
  one-day move × √days). The target is 80% of that move in the trade's favour, the stop 40% against (2 : 1 on the
  index), rounded to 5 points.
- **Filters.** Each candidate is checked like an AI proposal: defined risk, legs on the chain. It is dropped if:
  - a leg has no live two-sided quote;
  - it does not make money at the target and lose at the stop.
- **Pricing.** At the bid / ask, with the premium target and stop per leg (Black-Scholes, as in PA-24), P&L per lot,
  charges and warnings.
- **Ranking.** By the PA-26 evidence score, then by profit-to-loss at the levels. Short reasoning is generated for
  each trade: the rule, the strikes' distance from the money, buying vs selling premium, and the exit plan.
- **Endpoint:** `GET /api/rank/{symbol}?expiry=`. Returns the top 8, with how many candidates were considered.

### The AI strategist section

1. **Ranked trades — best first.** One row per trade:
   - rank and score;
   - the trade and its direction;
   - the orders in Dhan's naming (BUY / SELL NIFTY 27 OCT 22600 PUT);
   - entry, target and stop-loss premium per leg;
   - the NIFTY target / stop;
   - ₹ per lot at the target and at the stop;
   - profit : loss.

   It loads with the chain, follows the chosen expiry, and refreshes every minute while the market is open (unless a
   ticket is open). It also has a Refresh button.
2. **Detail card.** Tapping a row opens the same card as an AI suggestion, labelled "Pulse ranked trade #n": the
   plain-language plan, the Dhan orders, the leg ticket, the economics and the Take button. Its lines are drawn on
   the chart (labelled "#n target", "#n stop"). The top-ranked trade is shown by default.
3. **Second opinion from the AI.** The GPT-5 button is unchanged. Its answer shows in the detail area, with a link
   back when a ranked trade was selected.

## 3. Tests

- `test_rank_builds_tradable_defined_risk_trades_best_first`:
  - scores are in descending order, and bearish trades lead when the data are bearish;
  - every candidate passes the structure check;
  - every candidate makes money at the target and loses at the stop, with the index levels on the correct sides;
  - the ranks run 1…n;
  - long options and debit spreads in both directions are present.
- Unit suite: 1,508 passed. Ruff is clean, and `node --check` passes.

## 4. Verification

Live on 2026-10-26 at 10:18, NIFTY 22,669: 16 tradable candidates.

| Rank | Score | Trade | Per lot at target / stop |
|---|---|---|---|
| #1 | 92 Strong | Sell 22700 CE / buy 22800 CE | +₹1,144 / −₹575 |
| #4 | 72 | Buy 22600 PE (entry ₹76.30, target ₹163.25, stop ₹47.30) | +₹5,652 / −₹1,885 |

NIFTY target 22,500, stop 22,755. A screenshot with #4 selected was checked.

## 5. Risks and open items

- The 80% / 40% index levels are a fixed rule, not fitted.
- Ranking by score favours the data's direction; within a band, profit : loss decides. A score is agreement, not a
  proven edge.
- Ranked trades are not auto-recorded in the AI track record. Only GPT-5 suggestions are; take a ranked trade to
  record it.
- Premium targets and stops are same-day estimates.
