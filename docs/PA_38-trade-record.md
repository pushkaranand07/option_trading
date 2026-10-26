# PA-38 — Trade Record: take the AI's trade as a dummy trade, monitor it, keep a P&L history

| | |
|---|---|
| **Status** | Done |
| **Scope** | new `webapp/trade_record.py`, `webapp/server.py` (`/api/trades*`, background monitor), `webapp/static/*` (Take button on the Plan tab, new Trade Record tab), `tests/test_trade_record.py` |
| **Related** | [PA-34](PA_34-ai-strategist-and-nse-option-chain.md), [PA-36](PA_36-trade-ticket-and-premium-levels.md), [features/webapp](features/webapp.md) |
| **Pull request** | branch `feature/trade-record` |
| **Date** | 2026-10-26 |

## 1. Problem

The user asked for three things:

- a way to take the AI strategist's trade from the Plan tab as a dummy trade;
- monitoring of the trades taken;
- a tab with the trade history and its profit and loss.

## 2. Decisions (user)

| Question | Choice |
|---|---|
| Target or stop reached | **Only alert** — the trade stays open until the user closes it |
| Lots | **Always 1 lot** |
| Tab name | **Trade Record** |

## 3. Design

### Taking a trade

The Plan tab's AI card has a button: **Take this trade (dummy, 1 lot)**. It stores the suggestion as an open trade
in `reports/trade_record/trades.json` (git-ignored; stays on this computer). The stored trade has:

- the time taken, instrument, expiry, strategy and bias;
- the index entry zone, target and stop, and the index level at entry;
- each leg at the price the strategist used (buy at the ask, sell at the bid), with its target and stop premium;
- the worst and best case, and the charges.

A no-trade or refused suggestion cannot be taken. Once taken, the button shows "Recorded ✓" with a link to the tab.

### Monitoring

- **Close-out prices.** Open trades are marked from the NSE chain at the price each leg could be closed at now: a
  bought leg at the bid, a sold leg at the ask (last price if a side is empty). This gives the live P&L per leg and in
  total, and the index now.
- **Flags.** When the index reaches the target or stop, the trade is flagged and the flag is saved with its time, the
  index level and the P&L then. After expiry it is flagged "expired".
- **Never closed automatically.** The user closes each trade.
- **Background check.** A thread in the server checks open trades once a minute while the market is open, so a
  target or stop reached while the page is closed is still recorded.

### Closing

- **Close trade.** Settles at the live close-out prices. After expiry it settles at intrinsic value from the last
  index level seen.
- **What is recorded:**
  - gross P&L;
  - charges for opening and closing every leg (no exit charge for an option that expired worthless);
  - net P&L;
  - the reason: "target reached", "stop reached", "closed by you" or "expired".
- **Remove** deletes a trade taken by mistake.

### The Trade Record tab

- **Summary:** total net P&L of closed trades, open trades and their P&L now, closed count, won / lost, win rate,
  average, best and worst.
- **Open trades:**
  - live P&L;
  - flag banners;
  - the index ladder (target, now, stop);
  - each leg's entry, current close-out price, target, stop and P&L;
  - Close and Remove buttons.
- **History:** taken and closed times, trade, legs (entry → exit), index in → out, why it was closed, gross, charges,
  net.
- **Refresh:** every 15 s while the tab is open.

## 4. Tests

`tests/test_trade_record.py` has 5 tests:

- **Taking:** a trade is stored with its entry and premium levels; a no-trade or refused suggestion is rejected.
- **Marking:** the close-out price is used for each leg; reaching the target only flags the trade, and the flag is
  remembered after the price moves back.
- **Closing:** gross, charges and net are booked, the reason is recorded, and the totals and win rate update; closing
  twice is refused.
- **Expiry:** after expiry the trade is flagged without asking for a chain, and settles at intrinsic value.
- **Remove:** a trade can be deleted, and an unknown id is refused.

Ruff is clean, and `node --check` passes.

## 5. Verification

Live on 2026-10-26 during market hours:

- **The AI's proposal:** a bear call spread, sell 22600 CE at 92.50 / buy 22700 CE at 58.65; NIFTY target 22,350,
  stop 22,640.
- **Taken** at 09:33 through the API. At NIFTY 22,447.55 the trade was marked at 88.30 / 55.30, a P&L of **+₹55**.
- **Screenshots:** the Trade Record tab and the Plan tab's Take button.
- The test trade was then removed, so the record starts empty.

## 6. Risks and open items

- Paper fills at the quoted bid / ask; real fills can be worse.
- Charges assume Dhan's flat ₹20 per order plus statutory charges.
- After expiry, the settlement uses the last index level the monitor saw, not NSE's official settlement price.
- Monitoring runs only while the web server is running.
