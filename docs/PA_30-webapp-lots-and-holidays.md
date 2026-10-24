# PA-30 — Web app: live lot sizes and a holiday-aware market status

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/market_data.py` (`INDICES`, `load_index_lots`, `index_lots`, `instrument`), `webapp/signals.py` (`market_open`, `nse_calendar`), `webapp/static/index.html`, `tests/test_webapp_market.py` |
| **Related** | [PA-02](PA_02-webapp.md), [PA-27](PA_27-calendar-special-sessions.md) (the calendar it now uses), [features/webapp](features/webapp.md) |
| **Pull request** | branch `fix/webapp-lots-holidays` |
| **Date** | 2026-10-24 |

## 1. Problem

Found while writing the docs:

- `market_data.INDICES` hard-coded index option lots — NIFTY 75, BANKNIFTY 35, FINNIFTY 65, MIDCPNIFTY 140 — and the
  help text said "One NIFTY lot is 75 units". Per-lot cost, risk and profit on the page used them.
- `signals.market_open` counted any weekday 09:15–15:30 IST as open, so NSE holidays showed as open.

## 2. Findings

Dhan's public scrip master (no login needed; the app already downloads it daily for equities) lists every index
option with `SEM_LOT_UNITS`. On 2026-10-24: **NIFTY 65, BANKNIFTY 30, FINNIFTY 60, MIDCPNIFTY 120, SENSEX 20** (also
BANKEX 30, NIFTYNXT50 25, SENSEX50 75). Three of the app's five lots were wrong.

## 3. Decisions

- Read the lot from the scrip master instead of maintaining a table: exchanges revise lots (NIFTY 75 → 65 in
  Jan-2026). During a revision old- and new-lot contracts coexist, so the **most common** lot per index is taken.
- Keep `INDICES` as a fallback for when the file cannot be fetched, corrected to the 2026-10-24 values.
- Market status from the NSE calendar ([PA-27](PA_27-calendar-special-sessions.md)): holidays closed, special
  sessions open, Muhurat days closed in regular hours. The calendar is fetched once a day.

## 4. Tests (first tests for the web app)

Lots parsed from a scrip-master sample (most common lot wins over an old-lot contract; stock options and equities
ignored); `instrument()` uses the live lot and falls back to the table; `market_open` on an ordinary Monday, after the
close, a weekday holiday, a Muhurat Sunday, a Budget Sunday and a Saturday. 8 tests pass.

## 5. Verification

Real scrip master parsed: NIFTY 65, BANKNIFTY 30, FINNIFTY 60, MIDCPNIFTY 120, SENSEX 20. `market_open()` on Saturday
2026-10-24 → False.

## 6. Risks and open items

- The web app is still separate from the NSE vendor layer for prices (Dhan / Yahoo).
- The `/api/ai` panel checks the Azure variables but builds the graph with the configured provider (noted in the
  feature doc; not changed here).
