# PA-32 — Prices: bars only on NSE sessions (2026-01-15 holiday bars removed)

| | |
|---|---|
| **Status** | Done |
| **Scope** | `tradingagents/analytics/prices.py` (`price_sessions`, `drop_non_sessions`, `save_prices`), `scripts/quant_build_store.py`, new `scripts/quant_fix_price_sessions.py`, new `docs/data_catalog.md`, tests in `tests/test_quant_datastore.py`, `tests/test_research_store_pit.py`, `tests/test_research_import_guard.py` |
| **Related** | [PA-31](PA_31-research-splits-and-locked-loader.md) (the audit that found it), [architecture/11 — NSE data store](architecture/11-nse-data-store.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `data/fix-prices-holiday-bars` |
| **Date** | 2026-10-27 |

Research and decision support only, not investment advice.

## 1. Problem

The point-in-time audit in PA-31 failed in `prices`. Yahoo had bars on 2026-01-15, an exchange holiday (Maharashtra
municipal election), and the 2026-01-14 rows were stamped public on that holiday. The user asked for a data-integrity
fix: remove the bars without replacing them, correct `known_from`, add a regression test, check every other holiday,
log the correction, and measure which earlier results used the bars.

## 2. Root cause and findings

`save_prices` built its list of sessions from NSE's F&O days **plus every date Yahoo had a bar for**. A Yahoo bar on a
holiday therefore became a session, and the day before it was mapped to it.

**The whole dataset**, checked against NSE's holiday lists for 2018–2026 (with Muhurat days counted as sessions when NSE
published files):

| Pattern | Rows | Dates |
|---|---|---|
| Bars dated on a day with no NSE session | **29**, all `source = yahoo` | 2026-01-15 only |
| `known_from` on a day with no NSE session | **32** (29 stocks + NIFTY, BANKNIFTY, INDIAVIX) | trade date 2026-01-14 only |

All 29 bars are stocks; no index symbol had one. No other holiday had the pattern.

### Which earlier results used the bars (measured)

Counted from the inputs and the output files' dates; values in the locked holdout were not inspected, so the size of
each effect is **not measured**.

| Result | Used the bars? | How it was measured |
|---|---|---|
| GARCH / GJR / EGARCH forecasts (`vol_forecasts`) | **Yes**, all 29 stocks | 29 forecast rows dated 2026-01-15; **5,561** forecast rows dated on or after it come from return series that contain the bar. Index forecasts (NIFTY, BANKNIFTY, INDIAVIX): no |
| iv30 | No | Built from the option chain; 0 rows on 2026-01-15 |
| VRP condor (all variants, paper trading) | No | Uses NIFTY / BANKNIFTY prices, their GARCH and iv30 only: none had a holiday bar |
| Chronos | **Yes**, all 29 stocks | 29 forecast rows dated 2026-01-15; **5,537** rows on or after it |
| Regime HMM | No | The stock closes are reindexed to NIFTY's NSE dates before use, which drops 2026-01-15 (0 regime rows on it) |
| Quiet-stock condor (`quiet_stock_condor_garch`) | **Yes** | Picks stocks by their GARCH forecast; trial data to 2026-10-23 |
| MA trend, LightGBM (both), relative strength (both), move size, `random` baseline | **Yes** | Built on `evaluate.panel(load_prices(...))`, which keeps 2026-01-15 as a row; trial data ends 2026-04-22 to 2026-10-01 |
| Results-day fly, overpriced filter | **Yes** | The filter reads `adj_close`; 3 trades of the 29 stocks were open across 2026-01-15 and 78 entered after it |
| Results-day fly, plain | No | Uses the option chain only |
| Market Map | **Yes** | Reads all prices |
| `known_from` error (32 rows) | No earlier result | No earlier module filters prices by `known_from`; only the research loader (PA-31) does, and nothing has run through it yet |

Every earlier result that used the bars was already rejected or is not a trial (Market Map). The verdicts were not
re-run.

## 3. Decisions

| Question | Choice |
|---|---|
| Replace the removed bars? | No: removed, never interpolated or replaced (user) |
| Session list for prices | NSE's F&O days + F&O archive holes (2021-03-30 stays: it traded) + after the last published day, the days NSE's calendar counts as sessions (today's bar before tonight's files) |
| Correct the stored file now or wait for the nightly rebuild | Now, with `scripts/quant_fix_price_sessions.py`, so the correction is a logged event with counts; the nightly rebuild keeps it with the fixed code |
| 2021-03-30 partial rebuild | No (user); the second-source finding is in the [data catalog](data_catalog.md) |

## 4. What was built / changed

| Piece | Change |
|---|---|
| `prices.price_sessions` | The session list above |
| `prices.drop_non_sessions` | Splits bars into on-session and dropped |
| `prices.save_prices` | Keeps only on-session bars; `known_from` from the same sessions; optional `calendar` |
| `scripts/quant_build_store.py` | Drops and prints off-session bars; lists them in `quality_report.csv` as `dropped_non_session` |
| `scripts/quant_fix_price_sessions.py` | Applies the rule to the stored file without refetching; prints counts only; logs a `data_correction` event; `--dry-run` |
| `docs/data_catalog.md` | Started: holes, second sources checked, corrections, forward-only fields |

## 5. Tests

| Test | Proves |
|---|---|
| `test_a_yahoo_bar_on_an_nse_holiday_is_dropped_and_known_from_skips_it` | The 2026-01-15 case: bar dropped, 2026-01-14 public on 2026-01-16 |
| `test_an_archive_hole_stays_a_session` | Yahoo's 2021-03-30 bar is kept |
| `test_todays_bar_before_nse_files_is_kept_only_on_a_calendar_session` | A bar after the last F&O day is kept only if NSE's calendar says it was a session |
| `test_no_price_bar_or_known_from_on_a_day_without_an_nse_session` (opt-in, real store) | **Regression:** failed on the uncorrected store (2026-01-15), passes after the correction |

## 6. Results

- `prices`: 69,910 rows → 69,881. 29 bars removed (2026-01-15); 32 `known_from` corrected (2026-01-14 → 2026-01-16).
- Trial-log event 2 (`data_correction`), period `final_holdout`, values not inspected. `trial_count` unchanged (184).
- `scripts/research_check_pit.py` after the correction: **PASS**, 0 problem rows in every dataset.
- A second run of the fix script: "Nothing to correct."

## 7. Verification

The script's first real run wrote the file, then its trial-log call failed: the per-date counts had date keys, which
JSON cannot hold. The event was then written by hand with the counts that run printed (event 2 says so in its
`note`), and the script now checks that the log entry can be written before it changes the file.

## 8. Risks and open items

- **The nightly job runs whatever branch is checked out.** Until this PR is merged, a 19:30 run on `main` would rebuild
  `prices` with the old code and bring the 29 bars back. After the merge, the rebuild drops them on its own.
- **GARCH forecasts** are recomputed by the nightly job from the corrected prices. **Chronos outputs are not** (it is not
  in the nightly job): its 5,537 rows from 2026-01-15 on stay as computed.
- **Earlier trial results** that used the bars stay as recorded. All are rejected ideas; how much the bars moved them is
  not measured.
- `splits_v1.json` is frozen, so its known-issues entry for 2026-01-15 still reads "not fixed". This record and the data
  catalog supersede it.
