# PA-41 — Every Target / Stop loss shown can be typed into a Dhan Super order

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/static/app.js` (`legRole`, `legLevelsOk`, leg cards, ticket, ranked table, Trade Record), `webapp/static/style.css`, `webapp/strategist.py` (exit plan text of ranked trades), `tests/test_strategist.py` |
| **Related** | [PA-36](PA_36-trade-ticket-and-premium-levels.md), [PA-38](PA_38-trade-record.md), [PA-40](PA_40-pulse-trade-ranking.md) |
| **Pull request** | branch `fix/dhan-leg-orders` |
| **Date** | 2026-10-26 |

## 1. Problem

The user's bear call spread on the Trade Record tab showed, for the **BUY 22800 CALL**: entry 91.90, target 43.25,
stop loss 127.15.

- **Why it could not be entered:** Dhan's Super order for a BUY needs the target **above** the entry and the stop
  **below** it (the user's earlier Dhan screenshot: 88.80 → target 91.00, stop loss 86.60). So these numbers could not
  go into Dhan and read as wrong.
- **Why they were still right as estimates:** that call is the spread's protection. It is meant to lose a little when
  NIFTY falls to the target. As an estimate of the price at the index levels the numbers were right; as order boxes
  they were wrong.

## 2. Change

Each leg is shown by its job in Dhan:

| Leg | Dhan order | Target / Stop loss shown |
|---|---|---|
| Single option | **Super** order | Yes: a BUY has the target above the entry and the stop below |
| Credit spread (bear call, bull put), **SELL** leg | **Super** order | Yes: the target below the entry, the stop above |
| Credit spread, **BUY** leg (protection) | Limit, placed first | **none**: sell it right after the SELL leg's target or stop fills |
| Debit spread (bear put, bull call), iron condor | Limit; both closed by hand at the index levels, buying back the SELL leg first | Grey "(expected price at NIFTY target / stop)", for reference only |

A Super-order leg whose estimates break Dhan's rule falls back to the grey reference display.

Why there is no Super order on a spread's bought leg: if its stop loss fired alone, the sold leg would be left
naked.

### Where it applies

- Leg cards: a role tag (Super order / Protection / Close together), the Dhan boxes or the grey reference prices,
  and a note on how to place the leg.
- The "Manage as one trade" text.
- The ticket: order type, target / stop or "none", the expected prices, and the chart lines (grey for reference).
- The ranked table.
- The Trade Record's open-trade table, including trades recorded earlier.

The ranked trades' exit plan now says the same thing.

## 3. Tests

The ranking test now checks the exit-plan wording: a Super order on the SELL leg for credit spreads, and closing by
hand (buy back the SELL leg first) for the other spreads. Unit suite: 1,508 passed. Ruff is clean, and `node --check`
passes.

## 4. Verification

Screenshots of the Trade Record tab and the Plan ranking on 2026-10-26 at 10:31:

- **The user's bear call spread:** SELL 22700 CALL is a Super order (target 80.95 below the 146.75 entry, stop 190.75
  above); BUY 22800 CALL shows "none".
- **The user's bought put:** target 140.80 above the 63.55 entry, stop 38.50 below.
- **Ranked bear put spreads:** the leg prices appear in grey brackets.
