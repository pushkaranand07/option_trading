# Pipeline audit

> **Status:** Run 2026-11-01. Thresholds were written before the run and not tuned on results.
> **Scope:** past defects, sanity checks on the real feature tables, development only, and 5 headline numbers recomputed by a second code path.

Research and decision support only, not investment advice. **Cost model unverified.** This is a check of specific defect classes, not proof the pipeline has no other error.

## Past defects and the check that would have caught each

| Defect | Where | Class | Check now |
|---|---|---|---|
| GARCH inputs in fractions | `features.garch_one`, PR 66 | Units | Median range, `check_ranges` |
| ADANIENT action filtered out | Rule A's kinds, PA-40 | Discontinuity with a listed subject | Test: a scheme blanks the session |
| Holiday bars on 2026-01-15 | `prices`, PA-32 | A row on no session | Test: no row on a session with no data |
| Lot despike could flip alternating blips | `base_store`, PA-35 | Non-converging repair | Test: repair is stable on repeat |
| Rule table added percent to a fraction | `research_gate2_addendum4`, PA-45 | Units | Test: percent becomes a fraction |

Planted bugs (unit error, one-day look-ahead, stale feature) are run by `tests/test_pipeline_sanity.py`; each must be caught.

## Feature tables

Range check: **PASS**, 0 problems.


Stale check, limit 50%: **FAIL**, 2 problems.

- d: dii_opt_idx_call_net: 99% of values equal the previous session
- d: dii_opt_idx_put_net: 99% of values equal the previous session

## Five numbers, two code paths

| Number | First path | Second path | Allowed difference | Result | How |
|---|---|---|---|---|---|
| trial count | 1535 | 1535 | 0 | **PASS** | Trial log's function against a direct SQL sum |
| U1 series, 2022 | 100 | 100 | 0 | **PASS** | Rule's 100 against the stored membership's distinct series; those series carry 103 symbols through renames |
| always long, h = 1 | -0.277148 | -0.277225 | 0.02 | **PASS** | Stored gross against own rebuild from `base_futures`, % net at 1.5x, 284,085 rows |
| f rank, h = 1 | -0.1635 | -0.1635 | 0.002 | **PASS** | Stored result against saved predictions, % net; no one-open rule needed at h = 1 |
| parity flag rate at 25 contracts | 0.006444 | 0.00644368 | 1e-06 | **PASS** | Corrected figure in the threshold report against own join of the chain |

## Corrections made by this audit

- **U1:** the first version of this check compared 100 to 103 distinct symbols and failed. The rule ranks series, not symbols: the stored membership has 100 series, carrying 103 symbols through renames, and 100 of the top 100 symbols by own 2021 ranking are members. The flaw was in the check; the universe is right.
- **Parity rate:** Step 1 loaded each year by `known_from`, then filtered by `trade_date`, so each year's last session fell out of both years. Excluding those sessions, the second path gives 0.00646266, Step 1's original 0.646%. With them it is 0.00644368, reported as **0.6444%**. It stays at or below 1%, and 10 contracts' 1.77% stays above it, so **the threshold of 25 does not change**.
- **Stale flags:** `dii_opt_idx_call_net` and `dii_opt_idx_put_net` sit at or near 1, so they repeat. This looks like DIIs holding almost no short index options, not data carried forward. That reading is not verified against another source.
