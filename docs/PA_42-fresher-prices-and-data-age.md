# PA-42 — Fresher option prices, and every price says how old it is

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/option_chain.py` (cache 30 s → 10 s), `webapp/trade_record.py` (`as_of`), `webapp/static/app.js` (chain refresh 30 s → 15 s, `nseAge`, labels), `tests/test_trade_record.py` |
| **Related** | [PA-34](PA_34-ai-strategist-and-nse-option-chain.md), [PA-38](PA_38-trade-record.md) |
| **Pull request** | branch `fix/fresher-prices` |
| **Date** | 2026-10-26 |

## 1. Problem

The user found the updates slow. The Trade Record showed NIFTY 22,548 and the 22550 PE at 96.40, while the chain on
the Plan tab showed 22,559 and 93.80.

## 2. What was measured

Live on 2026-10-26, 11:44–11:46, NSE's `option-chain-v3` was fetched every 20 s:

| Fetched at | NSE timestamp | Age when fetched |
|---|---|---|
| 11:44:45 | 11:43:48 | ~57 s |
| 11:45:05 | 11:44:29 | ~36 s, then unchanged for ~45 s |
| 11:46:06 | 11:45:14 | ~52 s |

Findings:

- **NSE's free chain** updates about every 45 s, and each snapshot is already 30–60 s old. A fetch takes 0.1–0.7 s,
  so the delay is NSE's, not the network's.
- **Yahoo's NIFTY quote** changed on every call (near real time).
- **Pulse added up to about a minute on top:** a 30 s server cache plus a 30 s page refresh.
- **The two screens show different prices by design.** The Trade Record shows the price a leg could be closed at (the
  bid for a bought option), while the chain shows the last traded price. The two were also fetched at different
  moments.

## 3. Change

- **Server chain cache:** 30 s → **10 s**.
- **Plan tab chain refresh** in market hours: 30 s → **15 s**. The Trade Record already refreshes every 15 s.
- **The age of every price is shown:**
  - the chain header reads "NSE data as of 11:44:29 (52 s ago) · NSE updates about every 45 s";
  - each open trade reads "prices from NSE as of 11:44:29 (… ago)" (`as_of` in the live mark).
- **"Now (to close)" is explained** in a tooltip: bid for a bought option, ask for a sold one, not the last traded
  price.

The worst-case extra delay from Pulse drops from about 60 s to about 25 s. NSE's own 30–60 s cannot be removed with
its free data.

## 4. For real-time prices

The Dhan API (`DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN` in `.env`) gives live quotes and option chains. The web app
already uses Dhan for candles and quotes when it is configured. Moving the option chain and the Trade Record marks
to Dhan is the next step once the user's token is available.

## 5. Tests

`test_live_marks_carry_the_time_of_nses_snapshot`. Unit suite: 1,509 passed. Ruff is clean, and `node --check`
passes.
