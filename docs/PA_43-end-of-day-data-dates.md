# PA-43 — Risk, Options costs and Research say which close their data is from

| | |
|---|---|
| **Status** | Done |
| **Scope** | `webapp/quant.py` (`freshness`, attached to `risk`, `spreads`, `research`), `webapp/static/app.js` (`freshLine`), `webapp/static/style.css`, `tests/test_webapp_quant.py` |
| **Related** | [PA-32](PA_32-webapp-tabs.md), [development/scheduled-job-operations](development/scheduled-job-operations.md) |
| **Pull request** | branch `feature/data-dates` |
| **Date** | 2026-10-26 |

## 1. Problem

On Monday 2026-10-26 at about 12:00, the user reported that the Risk tab and the other tabs were "not updated
according to the current date".

## 2. What was checked

| Tab | Data from | |
|---|---|---|
| Today / Plan chart | today 11:55 (Yahoo, live) | current |
| Risk & Volatility (regime, GARCH, expected move, IV) | Fri 23-Oct close | the latest that exists |
| Options → measured spreads | Fri 23-Oct close | the latest that exists |
| Research → nightly job | ran Fri 23-Oct 20:52, OK; next run Mon 26-Oct 19:30 | as scheduled |

- **The data were correct.** These tabs use NSE's official end-of-day files, which are published after the close and
  downloaded by the 7:30 PM job. Friday was the last completed session.
- **The page didn't explain it.** It showed "as of 2026-10-23" without saying why, so it looked out of date.

## 3. Change

- **`quant.freshness(as_of, now, calendar)`**, using the NSE calendar. It returns:
  - the session the data covers;
  - the latest session it could cover by now (today only after 22:00 on a trading day, otherwise the previous
    session);
  - whether the data are **stale**;
  - when the next 7:30 PM update is due (skipping weekends and holidays).
- **Where it is attached:** `risk()` (the GARCH / regime / IV date), `spreads()` (the quote snapshot) and
  `research()` (the session the last nightly run covered).
- **The line on each tab.** The Risk tab, the Options tab's costs card and the Research tab now open with "End-of-day
  data from **Fri 23 Oct** — the latest NSE close (today's data comes after the market closes). Next update **today
  7:30 PM**. Live prices are on the Plan and Today tabs." When the data are stale it turns into a warning to check the
  nightly job.

## 4. Tests

`test_end_of_day_freshness_knows_the_latest_close_and_the_next_update`, with a fixed calendar, covers:

- Monday morning showing Friday's data: current;
- a missed Monday night: stale;
- a weekend;
- the evening before a holiday: the next update skips the holiday;
- no date at all.

Unit suite passes. Ruff is clean, and `node --check` passes.

## 5. Verification

`/api/risk/NIFTY` at 2026-10-26 12:xx: `as_of 2026-10-23`, not stale, next update "today 7:30 PM". The Risk tab was
checked in a screenshot.
