# PA-34 — AI strategist and NSE option chain in the Plan tab

| | |
|---|---|
| **Status** | Done |
| **Scope** | new `webapp/option_chain.py`, new `webapp/strategist.py`, `webapp/server.py` (`/api/chain`, `/api/strategy`), `webapp/static/*` (Plan tab), `tests/test_strategist.py` |
| **Related** | [PA-33](PA_33-morning-plan.md) (Plan tab), [PA-23](PA_23-option-quotes-measured-spreads.md) (measured spreads), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/ai-strategist` |
| **Date** | 2026-10-24 |

## 1. Problem

The user asked for the Plan tab to analyse the selected instrument with AI and propose an options strategy for their
own capital and risk. They supplied a screenshot of their trading app's option chain as the model for the chain.
The request covered:

- a chart with levels;
- an AI analysis (chart, indicators, data and the fundamentals view);
- an option chain like the app's;
- the choice between buying and selling, and of strikes, with reasons;
- entry, target and stop drawn on the chart.

## 2. Design

### Option chain (`option_chain.py`)

- **Source:** NSE's public API (`option-chain-contract-info`, `option-chain-v3`). It works without a broker login, for
  indices and F&O stocks.
- **Units:** OI and volume are shown in units (contracts × lot), as Indian apps do.
- **Per strike:** put-call ratio (PCR).
- **Call / put walls:** taken from the strikes shown (±15 around the money). Far strikes carry record OI that says
  little about the coming days.
- **Summary:** max pain and ATM IV.
- **Lot size:** from the Dhan scrip master for indices and the NSE F&O store for stocks.
- **Cache:** 30 s.
- **SENSEX:** listed on BSE, so it gets a clear message and no chain.

### AI strategist (`strategist.py`)

One structured GPT-5 call (`with_structured_output`). It reads:

- trend, averages, 52-week position and the last sessions;
- today's intraday rule checks and the rule's record;
- the GARCH expected move, the regime, and implied vol vs the forecast;
- PCR history and FII positioning;
- the 8:30 AI view, if there is one;
- the chain summary and ±8 strikes with bid / ask / OI / IV;
- the research notes: no validated edge, measured spreads, and that selling around results failed.

It returns:

- a market read, a bias and a confidence;
- a strategy from a fixed menu: no trade, long call / put, the four vertical spreads, or an iron condor;
- the legs;
- the buy-vs-sell and strike reasoning;
- the underlying's entry zone, target and stop;
- an exit plan, key levels and risks.

### What the code checks, prices and sizes

- **Structure check.** The legs must match the named strategy and be on the chain. Every sold option needs a bought
  option of the same type further out of the money (proof plan: defined risk only). Otherwise the page shows the
  proposal as refused.
- **Pricing at the live bid / ask.** Buy at the ask, sell at the bid, and fall back to the last price if a side is
  empty. The code works out the net premium, max loss and max profit per lot, the break-evens and the
  reward-to-risk.
- **Sizing.** The most lots whose max loss **plus Dhan charges** (every leg opened and closed) stays within the user's
  limit, and whose outlay fits the optional "money for this trade". Zero lots shows as "too big for your limit".
- **Warnings.**
  - Reward under half the risk ("must work N% of the time to break even").
  - Target and stop on the same side of the entry.
  - A leg without a live quote.
- **Capital never goes to the LLM.** Only the risk % does; rupee sizing happens after the answer.

The call runs as a background job: `POST /api/strategy`, then poll `GET /api/strategy/{id}`. It takes about 50 s. The
browser keeps the job id, so a page reload still shows the result.

### Plan tab

There is a new "Money for this trade" input beside capital and max loss.

Each instrument card shows, in order:

1. Today's call.
2. The chart. It now also draws the call / put walls and the AI's entry zone, target and stop.
3. **AI strategist.** A button, then a result card with:
   - the levels;
   - the priced legs and the per-lot economics;
   - the lots for your limit;
   - warnings, reasoning, key levels and risks.
4. **Option chain**, with:
   - expiry pills;
   - PCR, walls, max pain and ATM IV;
   - OI, volume and IV views, with bars and the top 3 per side in bold;
   - the change under each value, per-strike PCR, ITM shading and the spot line;
   - the AI's BUY / SELL strikes tagged.
5. The morning view.

Picking another expiry in the chain makes the next AI run use it. The chain refreshes every 30 s while the market is
open.

## 3. Tests

`tests/test_strategist.py` has 5 tests:

- **Structure:** naked, malformed and off-chain structures are refused; an iron condor and no-trade are accepted.
- **Pricing:** at bid / ask for credit, debit and long options, with break-evens.
- **Sizing:**
  - stays within the limit including charges;
  - the allocation cap applies;
  - the zero-lot case.
- **`recommend` with a fake LLM:**
  - the rupee limit is not in what the LLM sees;
  - poor reward is flagged;
  - a naked sell is refused.
- **Chain shaping:** units, PCR, walls near the money, max pain.

Unit suite: 1,494 passed. Ruff is clean, and `node --check` passes.

## 4. Verification

Checked live on Saturday 2026-10-24, with NSE serving the 23-Oct closing book.

- **NIFTY 27-Oct chain:**

  | Spot | Lot | PCR | Call wall | Put wall | Max pain | ATM IV |
  |---|---|---|---|---|---|---|
  | 22,600 | 65 | 0.74 | 23,000 | 22,000 | 22,700 | 14.3 |

  The 22,600 CE last price of 132.45 (−80.35) matches the user's screenshot.
- **Stocks:** the HDFCBANK chain (lot 650) works. A non-F&O stock gets "has no options on NSE".
- **Two GPT-5 runs** (48 s and 57 s) both proposed a 22,900 / 23,000 bear call spread:

  | Credit | Worst case a lot | Best case a lot |
  |---|---|---|
  | ₹11.85 | ₹5,730 | ₹770 |

  The app flagged "must work about 88% of the time just to break even". With a ₹5,000 limit it sized 0 lots
  (₹5,833 with charges).
- **Prompt change:** afterwards the prompt was told to work out reward-to-risk from the bid / ask and to avoid such
  credit spreads.
- **Screenshot:** the Plan tab was captured with the result, the chart lines and the chain.

## 5. Risks and open items

- The AI's suggestions are not a tested strategy. Nothing here has an edge proven by the project's gates, and the page
  says so.
- Margin for credit spreads is approximated by the max loss; the broker's real margin can differ.
- Charges assume the exit happens at about the entry premium. Slippage beyond the quoted bid / ask is not added.
- NSE may throttle its API. The chain is cached for 30 s and refreshes automatically only on the Plan tab while the
  market is open.
