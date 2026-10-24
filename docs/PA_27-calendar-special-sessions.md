# PA-27 — The agents' NSE calendar knows special sessions (Budget days, Muhurat)

| | |
|---|---|
| **Status** | Done |
| **Scope** | `tradingagents/dataflows/vendors/nse/calendar.py` (`KNOWN_SPECIAL_SESSIONS`, `muhurat_days`, `from_nse`, `session_state`), `tests/test_nse_calendar_flows.py` |
| **Related** | [PA-19](PA_19-weekend-nse-sessions.md) (the same gap in the downloader), [architecture/07](architecture/07-india-market-layer.md) |
| **Pull request** | branch `fix/calendar-special-sessions` |
| **Date** | 2026-10-24 |

## 1. Problem

Found while writing the docs ([PA-26](PA_26-docs-restructure.md)): `NSECalendar` accepted `special_sessions`, but
`from_nse()` never filled it and no caller passed it. The calendar the agents' tools use (FII/DII flows, publication
status, "previous session") therefore treated the Sunday 2026-02-01 Budget session, weekend Muhurat sessions and the
2024 special live sessions as closed days.

## 2. Findings

- NSE's holiday master (`/api/holiday-master?type=trading`) covers **only the current year** (2026: 20 holidays).
- It marks a holiday with a Muhurat session with `*`: "Diwali Laxmi Pujan\*" on Sunday 2026-11-08.

## 3. Decisions

| Source | Used for |
|---|---|
| `KNOWN_SPECIAL_SESSIONS`: the 11 weekend sessions since 2015, each verified by NSE's own files ([PA-19](PA_19-weekend-nse-sessions.md)) | past dates (historical analyses) |
| holidays NSE marks with `*` → `muhurat_days` | upcoming Muhurat sessions, straight from NSE |

A Muhurat session is one hour at a time NSE announces separately (it varies by year), so it is **not modelled**: on a
Muhurat day `session_state` never says `open` in regular hours — `pre_market` before 15:30, `post_close` after (that
day's files are expected). Budget-day weekend sessions trade regular hours. If NSE is unreachable, the known sessions
still apply.

## 4. Tests

A fake holiday list with a `*` day: past Budget and Muhurat Sundays and this year's `*` day are sessions, an ordinary
holiday and Saturday are not; Muhurat-day states (10:00 → `pre_market`, 19:30 → `post_close`); a Budget Sunday is
`open` at 10:00; `previous_session(2026-02-02)` is the Sunday; with NSE down the known sessions remain. 23 calendar
and index-volume tests pass.

## 5. Verification

Live (cached) holiday list: `muhurat_days` = {2026-11-08}; 2026-02-01 and 2026-11-08 are trading days.

## 6. Risks and open items

- A future weekend session that is not a `*` holiday (e.g. a Budget on a Sunday) must be added to
  `KNOWN_SPECIAL_SESSIONS` — the downloader's weekend probe ([PA-19](PA_19-weekend-nse-sessions.md)) will reveal it.
