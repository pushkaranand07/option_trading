# PA-24 — AI trade explained like a broker order: premium levels per leg, leg ticket, chart marks

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/strategist.py` (`trade_levels`, Black-Scholes), `webapp/option_chain.py` (depth fields, `contract`), `webapp/server.py` (`GET /api/contract`), `webapp/static/*` (AI result card, ticket), `tests/test_strategist.py` |
| **Related** | [PA-23](PA_23-ai-strategist-and-nse-option-chain.md), [PA-22](PA_22-morning-plan.md), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/trade-ticket` |
| **Date** | 2026-10-25 |

## 1. Problem

The user compared the AI result with their Dhan app (screenshots of the chain, a contract's page, the order screen
and a Super order with target and stop loss). Two problems:

1. **The result looked wrong.** For a bear call spread it showed "Target 22,480, Stop 22,720". These are NIFTY levels:
   for a bearish trade the target is below and the stop above. Dhan's order screen works in option premiums, so the
   numbers read as backwards and could not be typed into the order.
2. **No detail per order.** The user asked that tapping one of the AI's orders (BUY or SELL) show its full detail —
   entry, target and stop loss as in Dhan — and mark it on the chart and the chain.

The user also suspected missing data. Checked against the app screenshot:

- Prices and bid / ask match exactly (22700 CE: last 88.80, bid 88.10, ask 89.95).
- OI is slightly lower (99.20 L vs 1.01 Cr) because NSE's live chain freezes at 15:40, while the app shows the final
  end-of-day OI.

## 2. Change

### Premium levels per leg (`strategist.trade_levels`)

- For each leg, the premium expected when the index reaches the AI's target and stop.
- Each premium is moved from the leg's live price by the Black-Scholes change between today's index level and the
  level. It uses the leg's own implied vol (ATM IV if missing), the days to expiry (at least half a day) and a 6.5%
  rate, and is rounded to the 0.05 tick.
- From these, the profit or loss per lot at the target and at the stop, per leg and in total.
- For spreads, the value of the whole spread now, at the target and at the stop.

### Live NSE data

- `option_chain` legs now carry the best bid / ask quantities, the total buy / sell quantities and NSE's contract id.
- `contract(id)`: the option's premium through the session from NSE's tick chart (`/api/chart-databyindex`, about
  10 s apart), with high, low, last and previous close. Exposed as `GET /api/contract?id=…`, cached for 30 s.

### The AI result card

- **Plain-language plan.** "You make money if NIFTY falls. These are NIFTY levels — watch the index", then three
  steps: enter between X and Y; book profit at T (≈ +₹ a lot); exit with a small loss at S (≈ −₹ a lot).
- **Price ladder.** Target, now and stop on one line, with the profit and loss zones coloured, so it is clear which
  side is which.
- **One card per order**, in Dhan's naming ("NIFTY 27 OCT 22800 CALL"): buy / sell at, target premium, stop-loss
  premium. A sold leg's card says its target is below the entry and its stop above.
- **Manage as one trade** (spreads):
  - close both legs at the spread's target or stop value, or when the index reaches the levels;
  - place the BUY leg first, for the margin benefit;
  - do not put separate stop losses on the legs: one firing alone leaves the sold option unprotected.
- **The ticket.** Tapping a card opens it; tapping again closes it. It shows:
  - the contract name, last price and change, high, low and previous close;
  - the premium chart with buy-at, target and stop-loss lines;
  - **How to place it in Dhan:** side, lot and quantity, order type, limit price, target, stop loss, and the money or
    margin needed. The order type is a Super order for a single-leg trade, and limit orders, exited together, for a
    spread.
  - **Market depth:** best bid and ask with their quantities, total buy and sell quantities, a bids-vs-offers bar,
    the spread, IV and OI. NSE publishes only the best level; Dhan shows 5.
- **The selected leg is marked:**
  - its strike row is highlighted in the option chain;
  - its strike is drawn as a line on the index chart, with the AI's entry, target and stop.
- Charges per lot are shown in the economics.
- The worst and best case are labelled "at expiry, if you never exit", to separate them from the planned exit.

## 3. Tests

Two new tests in `tests/test_strategist.py`:

- **Levels:**
  - for a bear call spread, both calls are cheaper at the target and dearer at the stop;
  - profit at the target, loss at the stop;
  - the spread is bought back cheaper at the target, and the per-lot P&L matches the spread values;
  - for a long put, the premium rises at the target;
  - no levels are given when the AI gives none.
- **Contract ticks:** high, low, last and previous close are read correctly, and a bad identifier is refused.

Unit suite: 1,496 passed. Ruff is clean, and `node --check` passes.

## 4. Verification

- **Your case** (sell 22600 CE, buy 22700 CE; target 22,480; stop 22,720; 2 days to expiry):

  | | Spread value | Per lot |
  |---|---|---|
  | Now | ₹42.50 credit | |
  | At target | ₹23.35 | ≈ +₹1,245 |
  | At stop | ₹64.30 | ≈ −₹1,417 |

  Per leg: the sold 22600 CE goes 132.45 → 83.70 at the target and 207.55 at the stop.
- **A new GPT-5 run** (84 s) proposed sell 22600 CE / buy 22800 CE, credit ₹74, target 22,450, stop 22,750:

  | Per lot | At target | At stop |
  |---|---|---|
  | P&L | ≈ +₹2,502 | ≈ −₹3,348 |

  No warnings were raised.
- **Screenshot** with the 22800 CALL ticket open: 2,192 NSE ticks, high 178.60, low 36.60, previous close 107.45,
  depth 1,040 @ 57.50 / 58.45 @ 390, 26% bids. The 22,800 row was highlighted and the strike line drawn on the index
  chart.

## 5. Risks and open items

- The target and stop premiums are estimates for a move today at today's implied vol. If IV changes or expiry nears,
  the real premiums differ. The index levels remain the primary signal, and the page says so.
- NSE's tick chart can miss the exact high and low (ticks about 10 s apart): 241.05 vs the app's 247.30 for the
  22700 CE.
- After the close, OI is NSE's 15:40 snapshot, not the final figure.

## Folded-in change (orders that can be typed into Dhan)

Merged here on 2026-10-26; the full text is in git history.

- **Legs by their job in Dhan.** A spread's protective BUY leg showed a target below its entry, which Dhan's
  Super order cannot take (a BUY needs target > entry > stop). Legs are now shown by role:

  | Leg | In Dhan | Target / stop loss shown |
  |---|---|---|
  | Single option; the SELL leg of a credit spread | **Super order** | Yes |
  | The BUY leg of a credit spread | Limit order, placed first | **none**; sell it right after the SELL leg exits |
  | Debit-spread and iron-condor legs | Limit orders, closed together by hand at the index levels (buy back the SELL leg first) | Grey, reference only |

  There is never a stop on a spread's bought leg: if it fired alone, the sold leg would be naked. The rule applies to
  the cards, the ticket, the ranked table, the Trade Record and the ranked trades' exit plan.
