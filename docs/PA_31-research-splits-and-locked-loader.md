# PA-31 — Data foundation step 1: frozen splits, locked research loader, point-in-time audit

| | |
|---|---|
| **Status** | Done |
| **Scope** | new `docs/data/splits_v1.json`, new `tradingagents/research/` (`splits.py`, `loader.py`), `tradingagents/analytics/trial_log.py` (events table), `tradingagents/dataflows/vendors/nse/calendar.py` (`ARCHIVE_HOLES`), `scripts/quant_build_store.py` (holes in the quality report), new `scripts/research_check_pit.py`, `scripts/research_freeze_splits.py`, tests `tests/test_research_*.py` |
| **Related** | [architecture/11 — NSE data store](architecture/11-nse-data-store.md), [architecture/12 — evaluation and validation](architecture/12-evaluation-and-validation.md), [plans/PROOF_PLAN.md](plans/PROOF_PLAN.md) |
| **Pull request** | branch `data/step-1-splits-and-loader` |
| **Date** | 2026-10-27 |

Research and decision support only, not investment advice.

## 1. Problem

The user asked for a data foundation for a statistical prediction model, built in steps, one pull request each. Step 1:
a development / validation / holdout split frozen with a hash, a loader that refuses the holdout unless it is unlocked
and the unlock is logged, and tests that fail if the point-in-time or holdout rules are broken. Before it: check every
missing NSE file against NSE's official holiday calendar.

## 2. Findings

### Missing weekday files vs NSE's holiday lists

NSE's `/api/holiday-master` answers per year with a `year` parameter (F&O segment for `fo` and `participant`, cash
market for `indices` and `mto`).

| Kind | Missing weekdays | Holidays | Unexplained | Result |
|---|---|---|---|---|
| fo | 168 | 167 | 1: 2021-03-30 | **FAIL** |
| indices | 176 | 167 | 9: 2015-02-02, 2015-03-12, 2015-03-13, 2015-05-19, 2015-07-08, 2015-09-04, 2015-10-16, 2015-12-01, 2016-06-20 | **FAIL** |
| mto | 133 | 133 | 0 | PASS |
| participant | 133 | 133 | 0 | PASS |

Every unexplained file returned 404 again on 2026-10-27 (for 2021-03-30 also in the UDiFF form). The other files for
those days exist, so they were sessions. They are **NSE archive holes, unrecoverable** (user's decision); the result
stays FAIL with that reason. The holiday API returns nothing for 2010 and 14 F&O holidays for 2011 (17–22 in other
years): 2010–2014 calendar checks are UNVERIFIED until step 2 builds them from NSE's yearly circulars.

mto and participant files were never downloaded for 2015-07 to 2017 (128–129 files in 2015, none in 2016–17). The
backward holdout does not use them; they are an optional backlog item.

### How 2021-03-30 is handled

| Table | 2021-03-30 | Effect |
|---|---|---|
| fo_summary, option_chain, participant, delivery, index_close, iv30 | no rows | The store takes its sessions from the F&O files, so the day is absent everywhere, even where the raw participant, MTO and index files exist. Rows of 2021-03-26 carry `known_from` 2021-03-31, one session late: conservative, no look-ahead. |
| prices | 32 rows, all Yahoo | NIFTY close 14,845.10 equals NSE's own index file for the day |
| vol_forecasts (GARCH) | 31 rows | Built from `prices`, so it has the day |
| VRP condor signal | — | `vrp_signal` runs on the chain's sessions; the z-score used on 2021-03-31 is the one from 2021-03-26 |
| Condor simulator | — | No mark that day; an exit decided on 2021-03-26 fills on 2021-03-31 |
| Trades open across the day | 0 | VRP pooled condor (frozen params), results-day fly, overpriced fly |

No value was interpolated or invented.

**Second source (one attempt).** NSE's own market activity report (`/archives/fo/mkt/fo30032021.zip`) and settlement
prices (`/archives/nsccl/sett/FOSett_prce_30032021.csv`) exist for the day. Checked on 2021-03-31 against that day's
bhavcopy: the report matches all 5,905 traded option contracts exactly (close, open interest, contracts: 100%), and
settle prices match 484 of 484 futures. But the report lists traded contracts only: it lacks 2,109 untraded contracts
that had open interest, and option settle prices, which the condor simulator uses for untraded legs. A 2021-03-30
rebuilt from it would be partial. **Not ingested**; the search is closed. Using it is a decision for the user.

### Point-in-time audit of the whole store (`scripts/research_check_pit.py`)

| Dataset | Rows | No `known_from` | Public on/before its session | Dated on a non-session | `known_from` later than the next session | Earlier |
|---|---|---|---|---|---|---|
| fo_summary | 67,673 | 0 | 0 | 0 | 31 (2021-03-26) | 0 |
| option_chain | 15,429,717 | 0 | 0 | 0 | 7,696 (2021-03-26) | 0 |
| participant | 10,915 | 0 | 0 | 0 | 5 (2021-03-26) | 0 |
| delivery | 63,307 | 0 | 0 | 0 | 29 (2021-03-26) | 0 |
| index_close | 6,549 | 0 | 0 | 0 | 3 (2021-03-26) | 0 |
| prices | 69,910 | 0 | 0 | **29** (2026-01-15) | 0 | **32** (2026-01-14) |
| iv30 | 66,317 | 0 | 0 | 0 | 31 (2021-03-26) | 0 |
| regime | 1,380 | 0 | 0 | 0 | 0 | 0 |

**Result: FAIL, in `prices` only.** 2026-01-15 was an exchange holiday (Maharashtra municipal election). Yahoo has 29
bars dated that day, copies of the previous close (RELIANCE ₹1,458.80 on both days), and the 32 rows of 2026-01-14
are stamped `known_from` 2026-01-15 instead of 2026-01-16. Both sit inside the locked final holdout. `prices` belongs
to the live pipeline, so it is **not fixed here**.

The audit's calendar counts a holiday as a session when NSE published F&O files that day (Muhurat sessions). NSE's 2025
list does not mark 2025-10-21 with "*", though NSE published every file: 2019-10-27, 2020-11-14, 2023-11-12,
2024-03-02, 2025-10-21 and 2026-11-08 are counted this way.

## 3. Decisions

| Question | Choice |
|---|---|
| 2025+ was already used by earlier tests | Locked anyway, labelled **"contaminated for ideas tested before 2026-10-27"**; a clean **forward holdout from 2026-10-27** added (user) |
| Where the lock lives | A separate research loader; the live pipeline, nightly refresh, paper trading and web app keep reading the store directly (user) |
| Unexplained gaps | Documented NSE archive holes, result kept FAIL; no other vendor's data labelled as NSE (user) |
| Which date decides the period of a row | `known_from`, not `trade_date`: a 2024-12-31 session first public on 2025-01-01 is a holdout row |
| Freezing | SHA-256 of the file's canonical JSON (sorted keys, no whitespace), so line endings cannot break it but any change of content does. A new split is a new file |
| Unlocks and the deflated Sharpe | Unlocks and the freeze go to a new `events` table in the trial log, so they never change `trial_count` |
| Derived tables without `known_from` | `vol_forecasts` and `chronos` are refused until they are stamped |

## 4. What was built

| Piece | What it does |
|---|---|
| `docs/data/splits_v1.json` | Development (earliest to 2022-12-31), validation (2023–2024), final holdout (2025-01-01 to 2026-10-26, locked, contaminated), forward holdout (2026-10-27 on, locked, pre-registered test only), the 2015-08-25 to 2021-04-04 backward regime check, the 19 earlier experiments that saw 2025+ with their date ranges, and the known data issues above |
| `tradingagents/research/splits.py` | Reads the file and refuses it if the hash differs from `SPLITS_SHA256`; periods, `period_of`, `last_open_day` |
| `tradingagents/research/loader.py` | `load(dataset, start, end, symbols, unlocks)`: selects by `known_from`, ends at 2024-12-31 by default, refuses a range touching a locked period without `Unlock`; the forward holdout also needs a pre-registration file committed to git and unmodified. Each unlock is logged **before** any row is read; if logging fails nothing is returned. Every load fails if a row lacks `known_from` or is public on or before its own session. `holdout_counts` gives rows per day in the locked periods, counts only |
| `trial_log.log_event` / `load_events` | The events table. Event 1, `split_freeze`, recorded on 2026-10-27 with the hash, the label and the 19 experiments |
| `calendar.ARCHIVE_HOLES` | The 10 days and their missing file kinds, with the reason. Data only: the calendar's behaviour is unchanged (they remain sessions) |
| `scripts/quant_build_store.py` | Adds one `nse_archive_hole` row per hole to `quality_report.csv` (from the next store build, e.g. tonight's 19:30 job) |
| `scripts/research_check_pit.py` | The audit above. Exit code 1 on FAIL |
| `scripts/research_freeze_splits.py` | Records the split in the trial log; skips a hash already recorded |

## 5. Tests

| File | Proves |
|---|---|
| `tests/test_research_splits.py` | The file matches its hash; any content change is refused, reformatting is not; periods are contiguous, only development and validation are open; the label and the five named experiment families are present |
| `tests/test_research_loader.py` | Default stops at 2024-12-31 by `known_from`; holdout refused without unlock and nothing logged; an unlock needs a reason; the unlock is logged and is not a trial; no read when logging fails; the final unlock does not open the forward holdout; the forward holdout needs a committed pre-registration; missing, same-day or earlier `known_from` fails the load; datasets without `known_from` are refused; `start` reads far enough back; counts need no unlock |
| `tests/test_research_import_guard.py` | Every file that reaches the store directly (imports `datastore`, `prices`, `backfill`, `holdout`, or uses `store_root`, `raw_root`, `data_cache_dir`) is in an explicit allow-list with a reason; research code may never be added to it; the guard catches five ways a model could read the store |
| `tests/test_research_store_pit.py` | Opt-in (`RESEARCH_STORE_DIR`): every row of every dataset on the real store passes the point-in-time check. 8 of 8 passed on 2026-10-27 |

Full suite: 1,689 passed, 14 skipped.

## 6. Results

- Split frozen: hash `c647d530…642a`, trial-log event 1.
- Real store through the loader: `fo_summary` by default returns 53,692 rows public 2018-01-02 to 2024-12-31 (last
  session 2024-12-30); a request to 2025-06-01 is refused with the contamination label.
- The forward holdout already holds one session: the 2026-10-26 close, public on 2026-10-27.

## 7. Verification

The holiday comparison, the 2021-03-30 measurements, the second-source check and the audit were run on the real store
and raw files on 2026-10-27; the numbers above are their output.

## 8. Risks and open items

- **`prices` FAIL (2026-01-15)** — needs a fix in the live price builder; waiting for the user's decision.
- **2021-03-30 partial rebuild** from NSE's market activity report — not ingested; the user's decision.
- **The 2015–2021 backward check sits inside development** and has been used once already: a regime check, not an unseen test.
- **Every period before 2026-10-27 has been seen by earlier experiments.** Development and validation are for building;
  only the forward holdout is clean.
- 2010–2014 calendar: UNVERIFIED until step 2. Backlog (optional, after steps 1–3): mto and participant files 2015-07 to 2017.
- Not yet provided by the user: Dhan tradebook, contract note, renewed Dhan token and Data API status.
