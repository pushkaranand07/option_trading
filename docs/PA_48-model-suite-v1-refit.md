# PA-48 — Model suite v1 after the GARCH fix: line of work closed

| | |
|---|---|
| **Status** | Done. **No edge found at a final trial count of 1,532.** Line of work closed, on the user's rule. Validation not read |
| **Scope** | new `docs/gate_v2_addendum_7.json`, `docs/models_v1_refit_report.md`; `tradingagents/research/features.py` (one line), `gate2.py`; `scripts/research_models.py`; tests; `docs/data_catalog.md` |
| **Related** | [PA-47](PA_47-model-suite-v1.md), [addendum 7](gate_v2_addendum_7.json) |
| **Branch** | `research/models-v1-refit` |
| **Date** | 2026-10-31 |

Research and decision support only, not investment advice. **Cost model unverified; slippage is an ASSUMPTION.** Nothing after 2022-12-31 was loaded for fitting or evaluation.

## 1. The bug

`features.garch_one` passed fractions where `garch_forecasts` expects percent. `garch_h1`, `garch_h5` and `garch_h10` were about 77 times too small at the median and scrambled: rank correlation with the correct values was 0.38 for RELIANCE and 0.08 for NIFTY. No look-ahead was found. It most likely lowered results, or added noise that could move a fit either way. Validation was not read in the first run.

The fix is one line, frozen in addendum 7, hash `f8a7b029…`, before the refit. Median `garch_h5` is now 0.330 against `rv_20` 0.312, and rank correlation with `rv_20` is 0.85, up from 0.17. Tables b to h are byte-identical; only table a changed. Old tables: `store/_snapshots/features_v1_before_garch_fix`. 277 of 309 symbols still fit, so the scale was not why 32 have no forecast; their cause stays UNVERIFIED.

## 2. Result

**0 of 30 development cells passed, as in the first run.** Full tables and the side-by-side: [models_v1_refit_report.md](models_v1_refit_report.md).

- **Primary horizons (h = 1, 2, 3):** only d CNN at h = 2 is positive, at +0.010%, with a lower bound of -0.445%. It flips sign across seeds and has 60% of folds positive.
- **Largest move in net expectancy:** 0.120 points. The verdict did not change in any cell.
- **Positive net expectancy, all failing:** [('d CNN', 2, 0.01), ('e ensemble', 5, 0.001), ('b LightGBM', 10, 0.433), ('d CNN', 10, 0.238), ('e ensemble', 10, 0.121), ('f rank', 10, 0.087)].
- **Closest:** f rank at h = 10, low power, clears items a, f and g with 80% of folds positive. Net +0.087%, lower bound -0.095%, so it fails item d. b LightGBM at h = 10 has the highest expectancy, +0.433%, and fails items d and g.
- **Unstable across seeds:** [('d CNN', 2), ('d CNN', 5), ('f rank', 5)].
- **Spec c:** with GARCH corrected, QLIKE is lower for GARCH than HAR at h = 1 (1.68 against 4.11). HAR's estimate comes from three windows of rv only. Spec c remains risk-only.

## 3. Leakage tests, before results were read

| Test | Result |
|---|---|
| Feature truncation, 7 dates | **PASS**: 102,042 cells, 0 different |
| Model truncation | **PASS**: 290 predictions per learner, 0 different; planted leak caught for all 5 |
| Shuffled, time-shift, stale | **PASS**: 51 cells, all traded, none passed |

Highest control net expectancy: -0.022% (time-shift, f rank, h = 10).

## 4. Trial count

| | Trials |
|---|---|
| Before model suite v1 | 1,389 |
| First run | 70 |
| Feature change | 3 |
| Refit | 70 |
| Validation reads | 0 |
| **Final** | **1,532** |

## 5. Closing

By the user's rule, this line of work closes with no further rescue. The finding covers these specs and features, this cost model and D-1 timing. It does not prove no edge exists. Nothing is registered for forward testing.

Open and unrelated to the verdict: `nightly_pinned.py --install` does not move the worktree first, and `schtasks` hung on the morning task. Both tasks are installed correctly, and neither has run pinned yet.
