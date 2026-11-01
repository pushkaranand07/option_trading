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
| trial count | 1532 | 1532 | 0 | **PASS** | Trial log's function against a direct SQL sum |
| U1 stocks, 2022 | 100 | 103 | 0 | **FAIL** | Rule's 100 against the stored membership's distinct symbols |
| always long, h = 1 | -0.277148 | -0.277225 | 0.02 | **PASS** | Stored gross against own rebuild from `base_futures`, % net at 1.5x, 284,085 rows |
| f rank, h = 1 | -0.1635 | -0.1635 | 0.002 | **PASS** | Stored result against saved predictions, % net; no one-open rule needed at h = 1 |
| parity flag rate at 25 contracts | 0.00646266 | 0.00644368 | 1e-06 | **FAIL** | Step 1 report against own join of the chain |

## Diagnosis of each FAIL, with no tolerance changed

- **U1 stocks, 2022:** the check compared 100 to distinct symbols. The stored membership has 100 distinct series and 103 distinct symbols, and 100 of the top 100 symbols by own 2021 ranking are members. A series can carry more than one symbol through a rename, so this is a flaw in the check if the series count is 100, not in the universe.
- **Parity flag rate:** Step 1 loaded each year by `known_from`, then filtered by `trade_date`, so each year's last session fell out of both years. Excluding those sessions, the second path gives 0.00646266 against the report's 0.00646266. **A small real defect in Step 1:** with them the rate is 0.00644368. It is still at or below 1% and above 10 contracts' 1.77%, so the threshold of 25 does not change.
