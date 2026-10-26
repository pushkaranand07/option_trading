# PA-15 — Weekend NSE special sessions downloaded (Budget days, Muhurat, special live sessions)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/backfill.py`, `tests/test_quant_backfill.py`, `scripts/update_progress.py`, `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-14](PA_14-market-map-2021-26.md) (the Market Map cross-check that found the bug), [PA-03](PA_03-quant-foundation-nse-data-store.md) (downloader and store), [PA-05](PA_05-garch-volatility-and-vrp-condor.md) (GARCH, IV), [PA-06](PA_06-regime-detection-hmm.md) (regime), [PA-13](PA_13-backward-holdout-2015.md) (2015–17 holdout files), [architecture/11-nse-data-store.md](architecture/11-nse-data-store.md), [architecture/13-volatility-and-regime-models.md](architecture/13-volatility-and-regime-models.md), [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) |
| **Pull request** | #19 and #20 (branch `quant/weekend-sessions`) |
| **Date** | 2026-10-24 |

---

## 1. Problem

NSE occasionally trades on a Saturday or Sunday: Union Budget days, Diwali Muhurat sessions and special live
(disaster-recovery) sessions. None of these sessions were in the data store, so any measurement touching them was
wrong or missing.

It was found when the Market Map's news cross-check ([PA-14](PA_14-market-map-2021-26.md)) could not match the
**Sunday 2026-02-01 Budget session**.

## 2. Root cause / findings

The backfill walked **Monday–Friday only** (`day.weekday() < 5`), so weekend sessions were never requested.

Every weekend since 2015 was then probed — **1,232** weekend dates, as recorded in PR #20 — and **11 real sessions**
were recovered:

| Kind | Sessions |
|---|---|
| Budget days | 2015-02-28, 2020-02-01, 2025-02-01, 2026-02-01 (Sunday) |
| Muhurat (Diwali) | 2016-10-30, 2019-10-27, 2020-11-14, 2023-11-12 |
| Special live sessions | 2024-01-20, 2024-03-02, 2024-05-18 |

## 3. Decisions

- **Probe, don't download everything.** A weekend is probed with one file, the index-close file (`WEEKEND_PROBE =
  "indices"`). The other files (F&O bhavcopy, participant OI, delivery) are fetched only if NSE traded that day. A
  normal weekend costs one request in the nightly job.
- **Download bar counts only the planned history.** `update_progress.py` counts the planned 2018+ weekday files; weekend
  files and the 2015–17 holdout files are extra, so they do not distort the bar.
- **No data committed** — the rebuilt store stays on the local machine.
- User decisions in these PRs: not recorded.

## 4. What was built / changed

| PR | Change |
|---|---|
| #19 | `backfill.py`: weekends are probed with the index-close file; the remaining kinds are fetched only if the probe file was published. A probed weekend is recorded in the manifest so it is not re-requested |
| #20 | `scripts/update_progress.py`: download bar counts only the planned 2018+ weekday history; a progress bar for the Market Map section. Tracker updated (weekend-session fix, Market Map section, rebuild done) |

Rebuilt locally after the download: store years **2019, 2020, 2023, 2024, 2025, 2026**, then implied vol (IV), GARCH
forecasts and the regime model.

## 5. Tests

`tests/test_quant_backfill.py`:
- A normal weekend costs one request and records nothing else (`test_backfill_saves_files_marks_holidays_and_probes_weekends_once`).
- A weekend special session is downloaded in full and not re-requested
  (`test_a_weekend_special_session_is_downloaded_in_full`).

Unit suite at PR #20: 1,333 passed.

## 6. Results

- 11 weekend sessions recovered and present in every dataset after the rebuild.
- The tracker's data-quality line now reads: every weekday and the 11 weekend special sessions present; 0 missing
  sessions in any dataset.

## 7. Verification

- The 2026-02-01 NIFTY close in the rebuilt store (24,825.45) equals the reported close.
- The Market Map was rebuilt with the recovered sessions; the Sunday 2026-02-01 Budget is now measured on its own
  session (NIFTY −1.96%) ([PA-14](PA_14-market-map-2021-26.md)).
- The nightly job now probes each weekend as part of its normal download step.

## 8. Risks and open items

- The probe relies on NSE publishing the index-close file for every session; a session with only some files published
  would be missed. Not recorded whether this has ever happened.
- Backtests and validations run before this fix (for example the VRP condor results in
  [PA-10](PA_10-retest-pooled-condor-and-relative-buffer.md) to [PA-13](PA_13-backward-holdout-2015.md)) used a store
  without these sessions. Whether they were re-run: not recorded.
- The 2015 and 2016 sessions fall in the holdout years (2015–17 files), which are kept outside the main store; how they
  are used there: not recorded.

## Folded-in change (calendar)

Merged here on 2026-10-26; the full text is in git history.

- **Special sessions in the calendar (2026-10-24).** `NSECalendar.from_nse()` never filled `special_sessions`,
  so the agents' tools treated Budget Sundays and Muhurat sessions as closed days. Two sources fix it:
  - **past dates:** `KNOWN_SPECIAL_SESSIONS`, the 11 weekend sessions since 2015, each verified from NSE's files (this
    record);
  - **upcoming Muhurat sessions:** NSE's holiday master marks them with `*` (e.g. "Diwali Laxmi Pujan\*", Sunday
    2026-11-08) → `muhurat_days`.

  The holiday master covers only the current year. A Muhurat hour is not modelled: on that day `session_state` reads
  `pre_market` before 15:30 and `post_close` after. A future non-`*` weekend session must be added to
  `KNOWN_SPECIAL_SESSIONS`.
