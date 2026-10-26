# PA-33 — Morning plan: ready before the open, a live call sized from your risk limit

| | |
|---|---|
| **Status** | Done |
| **Scope** | new `webapp/morning.py`, `scripts/morning_plan.py` + `.cmd`, `webapp/server.py` (`/api/morning*`), `webapp/static/*` (Plan tab), `tests/test_morning_plan.py`; Windows task "TradingAgents morning plan" |
| **Related** | [PA-32](PA_02-webapp.md) (tabs), [PA-27](PA_19-weekend-nse-sessions.md) (calendar), [features/webapp](features/webapp.md), [development/scheduled-job-operations](development/scheduled-job-operations.md) |
| **Pull request** | branch `feature/morning-plan` |
| **Date** | 2026-10-24 |

## 1. Problem

The user wants to open the app and find a plan already made: before the market opens the model should have studied
past history, news and trend lines; once the market opens it should say whether to take a trade, with what size and
risk, until the close (user).

## 2. Decisions (user)

| Question | Choice |
|---|---|
| Instruments | NIFTY and BANKNIFTY |
| AI agents (news, sentiment, debate) | Yes, for the two indices (~20 min of GPT-5 a day) |
| When | 08:30 on weekdays; holidays recorded, AI skipped |
| Sizing | Risk % of capital: the stop-loss loses at most that; leverage only as a consequence |

Also decided, and shown to the user before building:
- **Hours.** NSE trades 09:15–15:30 (pre-open 09:00); index derivatives move to a 15:45 close from 2026-12-07 under
  SEBI's closing-auction circular of 2026-10-15 — the plan follows that date.
- **No pre-decided trade.** The trade is decided live from 09:45 by the web app's history-checked rule; the morning
  plan supplies the context. No rule has passed the research tests, so "No trade" is the common answer and the trade
  card says it is not a validated edge.
- **Privacy.** Capital and risk % are kept in the browser (`localStorage`) and never sent to the server.

## 3. What was built

- `webapp/morning.py`: `session(day)` (trading day, holiday or Muhurat, times, next session); `context(symbol, day)`
  — trend and averages, last session, regime, expected day range (GARCH 5-day vol scaled to one day), implied vol vs
  forecast, PCR and FII index-futures long share from the NSE store (only data published before the day); `ai_view`
  — a full multi-agent analysis; `build` saves `reports/morning/<date>.json` (a data refresh keeps the morning's AI
  view; an AI failure is recorded, not raised).
- `scripts/morning_plan.py` (`--no-ai`, `--date`, `--log`), loading `.env` for the scheduled run; task registered for
  08:30 weekdays with the nightly job's settings.
- API: `GET /api/morning` (today's plan; built without AI if missing; `?date=` for a saved day), `POST
  /api/morning/refresh`, `POST /api/morning/ai` (background, one at a time).
- **Plan tab** (opens first): a live 5-minute chart per index (EMA 9 / 21, expected range for the day, entry / stop /
  target when there is a trade); the session bar with a live IST clock and phase (before the market → pre-open → wait
  until 09:45 → open, exit by 15:15 → closed); the risk-limit inputs; per index **Today's call** (wait / no trade with
  the reason / take this trade: option, entry, stop, target, lots, max loss, money needed, leverage — or "skip, one lot
  risks more than your limit") and the **Morning view** in plain words. Refreshes every 15 s while open.
  `?at=YYYY-MM-DDTHH:MM` previews the tab at a past moment with that day's saved plan.

## 4. Tests

Session times, the holiday and Muhurat cases and the 15:45 date; a build saves and reloads, runs the AI on trading
days only, keeps the AI view on a data refresh, and records an AI failure. 4 tests; unit suite passes; ruff clean.

## 5. Verification

Rules-only builds for 2026-10-23/24/26 (5 s each): NIFTY expected day range ±0.96%, PCR 0.81–0.88, FII long share 10%.
The Plan tab screenshotted at Saturday 16:03 (closed), and previews of 2026-10-23 at 08:40 (wait, countdown), 09:30 and
11:00 (live "No trade right now" with the reason). The scheduled task run on Saturday: result 0, log "market closed
(Saturday); next session 2026-10-26". First real run: Monday 2026-10-26 08:30.

## 6. Risks and open items

- The task runs the checked-out branch: `main` needs this merged before 2026-10-26 08:30, and the PC must be on.
- The take-trade card has not been seen with a live safe signal yet (none occurred while building); its sizing math is
  simple (lots = ⌊max loss ÷ (premium − premium stop) × lot⌋) but untested in the browser.
- The rule's costs (0.01% for indices) are optimistic for options; see the open item to use measured spreads.

## 7. Follow-ups (same day, from the user's review)

- A live 5-minute chart per instrument in the Plan tab (the Today tab's chart is unchanged).
- The index bar shows on every tab. On the Plan tab a click switches the plan to that instrument in place: NIFTY 50 and
  NIFTY BANK show the 8:30 plan with its AI view; other indices and searched stocks get the same view built on the spot
  (`GET /api/morning/context/{symbol}`; no AI — the AI Analysis tab runs it on request). Stocks are sized in shares.
  `?sym=FINNIFTY` in the address opens a given instrument.

## Folded-in change

Merged here on 2026-10-26; the full text is in git history.

- **PA-35 — risk-limit card removed (2026-10-25, user).** The Capital / Max loss % / Money-for-this-trade card was
  removed at the user's request.
  - Today's call and the AI strategist show **per-lot** figures (loss at the stop, premium, charges) and the user picks
    the number of lots.
  - `POST /api/strategy` takes only `symbol` and `expiry`; the LLM gets no risk input.
