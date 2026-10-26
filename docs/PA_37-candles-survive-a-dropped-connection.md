# PA-37 — Charts and the live call survive a dropped connection

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/market_data.py` (`_candles`, `_remember`, `_last_good`), `webapp/static/app.js` (data-source label), `tests/test_webapp_candles_fallback.py` |
| **Related** | [PA-32](PA_32-webapp-tabs.md), [PA-33](PA_33-morning-plan.md), [features/webapp](features/webapp.md) |
| **Pull request** | branch `fix/candles-fallback` |
| **Date** | 2026-10-26 |

## 1. Problem

The user's server log (2026-10-25) showed every `GET /api/candles/NIFTY` and `GET /api/plan/NIFTY` failing with
**502**, and yfinance printing `^NSEI: possibly delisted; no price data found`.

- **Cause:** the PC's internet / DNS was down at the time (the same session showed `ENOTFOUND`). Yahoo was simply
  unreachable.
- **Check:** on 2026-10-26 09:20 Yahoo returned NIFTY 5-minute and daily data normally.
- **Why it mattered:** the app turned a network blip into a blank chart and no live call.

## 2. Change

- **Saving good results.** Every successful Yahoo download of candles is kept:
  - in memory;
  - on disk, in `~/.tradingagents/cache/webapp_candles/<symbol>_<tf>.pkl`, at most once a minute per chart.
- **When Yahoo fails or comes back empty,** the last saved bars are served instead of an error. The data source then
  reads `saved (last bar 23-Oct 15:25)`, and the page says "No connection to the data source — showing saved (…)". A
  restart during an outage still has the copy on disk.
- **When nothing is saved yet,** the error now says so: "Yahoo unreachable and nothing saved yet".
- **Dhan is unchanged.** When Dhan is configured it is still tried first.

NSE as a second source was considered and not added: the failure was the PC's own connection, which NSE would not
survive either.

## 3. Tests

`tests/test_webapp_candles_fallback.py` has 2 tests:

- **Yahoo down after a success:** the saved bars are served with a "saved (last bar …)" label, including after the
  memory copy is cleared (the restart case) and when Yahoo answers empty.
- **Nothing saved and Yahoo down:** a clear error.

Unit suite passes. Ruff is clean, and `node --check` passes.
