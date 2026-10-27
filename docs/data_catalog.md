# Data catalog

> **Status:** In progress. Started in [PA-32](PA_32-prices-holiday-bars.md); the full table per dataset (source,
> frequency, range, row count, gaps, checks, checksum) comes with data-foundation step 7.
> **Scope:** the NSE store under `<data_cache_dir>/quant/store`, its raw files, and the derived tables.
> **Last verified against the code:** 2026-10-27

---

## 1. Holes: sessions whose NSE file is gone

Listed in code as `ARCHIVE_HOLES` (`tradingagents/dataflows/vendors/nse/calendar.py`) and in `quality_report.csv` as
`nse_archive_hole`. They stay sessions; the file kinds listed are absent. **Never fill them from another vendor and
label the result NSE data.**

| Session | Missing | Checked | Effect |
|---|---|---|---|
| 2021-03-30 | F&O bhavcopy | 404 in the legacy and UDiFF forms, 2026-10-27 | The store takes its sessions from F&O files, so the day is absent from every store dataset; 2021-03-26 rows carry `known_from` 2021-03-31 (one session late). `prices` and GARCH keep the day (Yahoo; NIFTY 14,845.10 = NSE's index file). No backtest trade was open across it. |
| 2015-02-02, 2015-03-12, 2015-03-13, 2015-05-19, 2015-07-08, 2015-09-04, 2015-10-16, 2015-12-01, 2016-06-20 | Index closes | 404, 2026-10-27 | Raw backward-holdout files only; the store's `index_close` starts 2018 |

### Second sources already checked (do not search again)

**2021-03-30, NSE's own market activity report** (`/archives/fo/mkt/fo30032021.zip`, with
`/archives/nsccl/sett/FOSett_prce_30032021.csv`). Both exist. Checked against the 2021-03-31 bhavcopy, the report
matches all 5,905 traded option contracts exactly (close, open interest, contracts) and the settlement file matches
484 of 484 futures settle prices. **Rejected (user, 2026-10-27):** the report lists traded contracts only. It lacks
the 2,109 untraded contracts with open interest and every option settle price, so a day rebuilt from it would look
complete without being complete. The hole stays.

## 2. Corrections

Each correction is logged in the trial log's `events` table (`kind = data_correction`) with the rows changed; values
in locked periods are not inspected.

| Date | Dataset | Change | Rows | Period | Trial-log event | Record |
|---|---|---|---|---|---|---|
| 2026-10-27 | prices | Bars dated on days with no NSE session removed (not replaced); `known_from` re-stamped from the same sessions | 29 removed (all 2026-01-15); 32 `known_from` corrected (all 2026-01-14) | final_holdout | 2 | [PA-32](PA_32-prices-holiday-bars.md) |

## 3. Forward-only fields

Collected from the day capture starts; no history exists or will be bought (user, 2026-10-27).

| Field | Since | Notes |
|---|---|---|
| Option bid / ask (closing book) | 2026-10-23 | `quotes.py`, 31 symbols × 3 expiries; intraday snapshots come with step 5 |
| Intraday option-chain snapshots | not started | step 5 |
| GIFT Nifty | not started | step 3 |
