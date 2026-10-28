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
| 2013-10-09 | F&O bhavcopy | 404 in the legacy and UDiFF forms, 2026-10-28; NSE's market activity report and MTO file for the day exist, so it was a session (not on any holiday circular) | Absent from the stored base; 2013-10-08 rows carry `known_from` 2013-10-09 (the hole counts as the session it was). Calendar check kept **FAIL** |
| 2015-02-02, 2015-03-12, 2015-03-13, 2015-05-19, 2015-07-08, 2015-09-04, 2015-10-16, 2015-12-01, 2016-06-20 | Index closes | 404, 2026-10-27 | Raw backward-holdout files only; the store's `index_close` starts 2018 |

### Second sources already checked (do not search again)

**2021-03-30, NSE's own market activity report** (`/archives/fo/mkt/fo30032021.zip`, with
`/archives/nsccl/sett/FOSett_prce_30032021.csv`). Both exist. Checked against the 2021-03-31 bhavcopy, the report
matches all 5,905 traded option contracts exactly (close, open interest, contracts) and the settlement file matches
484 of 484 futures settle prices. **Rejected (user, 2026-10-27):** the report lists traded contracts only. It lacks
the 2,109 untraded contracts with open interest and every option settle price, so a day rebuilt from it would look
complete without being complete. The hole stays.

**2013-10-09, NSE's own market activity report** (`/archives/fo/mkt/fo09102013.zip`, 83,310 bytes) exists, as does
the MTO file; the participant file does not. **Not used (user, 2026-10-28)**, for the same reason as 2021-03-30: a
traded-contracts-only day looks complete when it is not. The hole stays.

### Re-issued files

**2012-05-14** (`fo14MAY2012bhav.csv.zip`): the only one of 2010–2014's 1,243 files with two-digit years (`14-May-12`)
and a `*Updated` footer row; its CSV is dated 2012-05-22 09:29 inside the zip. A fresh download on 2026-10-28 is
byte-identical to the stored file, and no other URL form exists (`.csv`, `_old`, `/archives/fo/bhav/`: 404), so NSE
serves only this version; whether an earlier original existed is UNVERIFIED. **Used** (the only bhavcopy for the
day). Against NSE's market activity report for 2012-05-14: all 1,539 traded options match on close and open interest;
contracts differ on 75 index-option rows (NIFTY 60, BANKNIFTY 10, MINIFTY 5), the bhavcopy equal or higher (median
+0.3%, at most 2×). The raw file is kept as downloaded; the parser drops the footer row and reads the two-digit years.
No other file dropped a row.

## 2. Corrections

Each correction is logged in the trial log's `events` table (`kind = data_correction`) with the rows changed; values
in locked periods are not inspected.

| Date | Dataset | Change | Rows | Period | Trial-log event | Record |
|---|---|---|---|---|---|---|
| 2026-10-27 | prices | Bars dated on days with no NSE session removed (not replaced); `known_from` re-stamped from the same sessions | 29 removed (all 2026-01-15); 32 `known_from` corrected (all 2026-01-14) | final_holdout | 2 | [PA-32](PA_32-prices-holiday-bars.md) |
| 2026-10-28 | base_fo_summary | Derived lots despiked until stable (one pass could flip alternating blips around a lot change; the live store converges by despiking every night) | 877 `lot_size` values (2015: 449, 2016: 128, 2017: 62, 2018: 54, 2019: 48, 2020: 61, 2022: 65, 2023: 10), all UNVERIFIED | development, validation | 4 | [PA-35](PA_35-base-2018-2026.md) |
| 2026-10-28 | base_fo_summary | Lots despiked across the 2017/2018 batch boundary as one series | 6 (MRF, PAGEIND, SHREECEM), UNVERIFIED | development | 6 | [PA-36](PA_36-base-2010-2014.md) |
| 2026-10-28 | base_option_chain | Schema: `exercise_style = european` added to 2015–2026; row counts and every existing column identical | 0 values changed; 80,232,394 rows gained the column | all | 7 | [PA-36](PA_36-base-2010-2014.md) |
| 2026-10-28 | base_fo_summary | Lots despiked across the 2014/2015 boundary after the 2010–2014 ingest | 4 (2015), UNVERIFIED | development | 9 | [PA-36](PA_36-base-2010-2014.md) |

**2026-10-27 nightly run, `prices`:** 69,920 rows, 7 more than 69,881 + one new session (32). The 7 are Yahoo bars
that filled sessions missing before; every symbol now has one bar per session. **Their fill dates are UNVERIFIED**: no
copy of the file was kept before that run. From 2026-10-28 every rebuild or correction of the stored base snapshots
the file first (`<store>/_snapshots/`), so such changes can be traced to exact rows.

### Stale derived outputs (known, not rebuilt)

| Output | Stale from | Why it is not rebuilt |
|---|---|---|
| `chronos/<symbol>.parquet` for the 29 stocks that had a 2026-01-15 bar (5,537 rows) | 2026-01-15 | Built from the uncorrected prices. Chronos is rejected (QLIKE 0.382 vs GARCH 0.336) and is not in the nightly job, so its outputs are kept as they were and must not be used |

## 3. Stored base (every F&O underlying)

Built by `scripts/quant_build_base.py`; per-year rows, range, checksum and download dates in `<store>/base_manifest.json`.
Every lot is `UNVERIFIED` unless the file states it (UDiFF, from 2024-07-08); the research loader returns UNVERIFIED
lots in `lot_size_unverified` and leaves `lot_size` empty. The 2025+ rows are in the locked final holdout: built and
counted, never studied.

| Table | Years | Rows | Disk | Filter | Notes |
|---|---|---|---|---|---|
| `base_fo_summary` | 2010–2026 | 787,731 | 55.7 MB | every underlying | lots: 121,764 stated, 665,967 UNVERIFIED (659,839 derived from open interest, 6,128 none) |
| `base_option_chain` | 2010–2026 | 95,700,442 | 1,181.3 MB | ±25% moneyness, ≤70 days | `exercise_style`; `flag_parity`, `flag_below_intrinsic` (kept, never dropped). 2013-10-09 and 2021-03-30 are documented holes |

Quality results: [PA-34](PA_34-base-2015-2017.md) (2015–2017), [PA-35](PA_35-base-2018-2026.md) (2018–2026 and the
reconciliation with the live store).

### Which `known_from` is canonical for research

**The stored base.** 2021-03-30 was a real session (NSE published the participant, MTO and index files; only the
F&O bhavcopy is gone), so data from 2021-03-26 was public on 2021-03-30. The base stamps it so; the live
`fo_summary` / `option_chain` / `participant` / `delivery` / `index_close` / `iv30` stamp it 2021-03-31, one session
late (conservative, no look-ahead). Affected in the live store: the 2021-03-26 rows (31 summary rows, 7,696 chain rows
for the 31 symbols). The live store is **not changed** (user, 2026-10-28). **The research loader serves the base
tables only** and refuses every live table (`LiveTableRefused`, tested); live-pipeline code keeps its own access.

### What "reconciled with the live store" means for lots

The base's lots equal the live store's for the 31 shared symbols because both apply the **same derived method**
(open-interest GCD, then despiking until stable). That is consistency between two copies of one method, not
verification: every derived lot stays **UNVERIFIED** until checked against NSE circulars, and the research loader
returns them empty. Despiking raises an error, returning nothing, if it oscillates or does not settle in 50 passes.

### Bytes per row (`base_option_chain`, Parquet, measured)

| Year | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Bytes / row | 9.6 | 9.3 | 9.3 | 10.0 | 10.3 | 11.3 | 11.7 | 12.1 | 12.6 | 17.2 | 19.7 | 19.7 |

**Cause.** The column types are the same every year; what changes is how well the values compress. Two steps: a
gradual rise in 2018–2023 (more strikes and weekly expiries, more traded rows with non-zero prices), and a jump from
2024, when NSE moved to the UDiFF file format (2024-07-08). UDiFF states turnover in exact rupees where the legacy
format gave it rounded to lakhs: turnover alone went from 1.27 bytes/row (2018) to 3.84 (2025); open interest from 0.89
to 1.89; open / high / low from about 0.6 to 1.5. PA-33's disk estimates used one rate for every year and were wrong
(PA-35: 918.8 MB measured for 2018–2026 against ~0.6 GB estimated).

### 2010–2014 estimate (for batch c)

All 2010–2014 files are in the legacy format, like 2015–2017, so the 2015–2017 rate applies, not the UDiFF rate:

| | Estimate | Basis |
|---|---|---|
| Option-chain rows (filter A) | 13.2M | PA-33: 60 sampled files × estimated sessions. The same method was 11–15% **low** on 2015–2019 |
| Disk | **~123 MB** | 13.2M × 9.36 bytes/row (2015–2017 measured: 135,896,261 bytes / 14,526,511 rows) |
| Raw files | ~348 MB | PA-33 (sampled mean file size × estimated sessions) |

**Stop rule for batch c (user):** stop and report if measured rows exceed the estimate by more than 25% (over 16.5M),
or measured disk exceeds it by more than 25% (over 154 MB). Both gaps are reported either way.

### 2010–2014: estimate vs measured

| | Estimate | Measured | Gap | Stop limit |
|---|---|---|---|---|
| Option-chain rows (filter A) | 13.2M | 15,468,048 | +17.2% | 16.5M: within |
| Option-chain disk | ~123 MB | 126.3 MB | +2.7% | 154 MB: within |
| Summary disk | — | 12.4 MB | — | — |
| Raw F&O files | ~348 MB | 361.2 MB (1,243 files) | +3.8% | — |

### Exercise style

Stock options were **American** until the 2010-12-30 expiry and European from the 2011-01-27 expiry (NSE/faop/16165,
2010-10-28; NSE/faop/16588). Raw files: 5,547,532 American (`CA` / `PA`) rows, all 2010 stock options, last traded
2010-12-30; every one expires before 2011-01-27, and every European stock option of 2010–2011 (8,094,786) on or after
it. Index options were European throughout. In the stored chain (after the filter): 2010 has 2,739,572 American and
337,432 European rows; every other year is European. `exercise_style` was added to the 2015–2026 tables after a
snapshot, with row counts and every existing column identical (trial-log event 7).

**Rule:** any implied-vol or put-call-parity feature filters on `exercise_style == "european"`
(`loader.european_only`; `loader.require_european` raises otherwise, tested). American rows are never parity- or
intrinsic-tested in the base.

## 4. Open items (no decision yet)

| Item | Finding | Rule until decided |
|---|---|---|
| Put-call parity flags | Driven by thin trading. 2015–2017 tested pairs: thinner leg 1–9 contracts 16.1% flagged (91.7% of all flags), 10–99: 2.6%, 100–999: 0.2%, 1000+: 0.0%. Stock options 10.5%, index options 1.2%. Rate rises with distance from the money (2.5% within 2.5% of the future, 22.3% at 10–25%); days to expiry matter little (9–11%). Untraded rows are never tested | Any implied-vol feature needs a liquidity filter on **both** legs. The threshold is chosen in the feature-library step and pre-registered before any model sees results; not picked here |
| Large one-day moves (> 5σ) | 2015–2017: 51 of 455 explained by a split or bonus in NSE's corporate-action data; 9 have another action in the window; 323 stock moves and 72 index moves UNVERIFIED. 2018–2024: 53 of 957 explained (17 splits, 36 bonuses); 33 another action; 828 stock and 43 index moves UNVERIFIED | Flag only; no price adjusted. The unexplained moves are UNVERIFIED, not labelled as anything else |

## 5. Forward-only fields

Collected from the day capture starts; no history exists or will be bought (user, 2026-10-27).

| Field | Since | Notes |
|---|---|---|
| Option bid / ask (closing book) | 2026-10-23 | `quotes.py`, 31 symbols × 3 expiries; intraday snapshots come with step 5 |
| Intraday option-chain snapshots | not started | step 5 |
| GIFT Nifty | not started | step 3 |
