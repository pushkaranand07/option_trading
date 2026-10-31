# PA-47 — Model suite v1

| | |
|---|---|
| **Status** | Done. **No edge found at a trial count of 1,459.** One defect qualifies this (section 3). Validation not read |
| **Scope** | new `docs/gate_v2_addendum_6.json`, `docs/models_v1.json`, `docs/models_v1_report.md`; new `tradingagents/research/models.py`, `scripts/research_models.py`; tests; `docs/data_catalog.md` |
| **Related** | [PA-42](PA_42-feature-library-v1.md), [PA-45](PA_45-gate-v2-addendum-4.md) |
| **Pull request** | branch `research/models-v1` |
| **Date** | 2026-10-31 |

Research and decision support only, not investment advice. **Cost model unverified; slippage is an ASSUMPTION.** Nothing after 2022-12-31 was loaded for fitting or evaluation: validation (2023-2024) was not read, nor anything later.

## 1. Result

0 of 30 development cells passed (6 specs, with a in two forms, at 5 horizons; spec c is risk-only and has no direction). Full tables: [models_v1_report.md](models_v1_report.md).

- **Primary horizons (h = 1, 2, 3):** every net expectancy is negative. The best is d CNN at h = 2: -0.045%.
- **Closest cell:** b LightGBM at h = 10, labelled low power: +0.421%, lower bound -0.064%, 60% of folds positive (70% needed). It is positive mainly in high-VIX periods (+1.63%), with -0.48% in 2015-16. It failed items d and g. It does not go to validation, and no rescue is run.
- **The models do not beat a coin on the label.** Brier scores are about 0.25, and LightGBM's log loss at h = 1 to 3 is 0.700 to 0.707, against 0.693 for a constant.

Item d was at the 0.83rd percentile. Item e was report-only on development. Forward registration: none, so no file was written.

## 2. Order of work

Addendum 6 and `models_v1.json` were committed (`04f5e4b`) before any fit. Truncation and controls ran before any development result was read. Trial log: events 29 and 30 freeze the files; 70 trials logged, 7 rows x 5 horizons x 2 universes. Grid points are not separate trials under the stated definition: there are 4 per h for each a form and 2 per h for b, d and f.

## 3. Defect: `garch_h1`, `garch_h5` and `garch_h10` in `features_v1` are wrong

`features.garch_one` passes returns as fractions, but `volatility_model.garch_forecasts` expects percent. The values are about 77 times too small and were fitted on badly scaled data. The frozen spec's formula is right; the built table is wrong. This is my error from PR #66. The feature catalog's 0.9999+ correlation between these three was flagged but not investigated.

- **Affected:** 3 of 112 inputs, in specs a, b, d, e and f. The development GARCH baseline (report-only) and spec c's GARCH comparison.
- **Not affected:** the gate's baselines in `addendum4_schedules`, which use the correct path.
- **Measured:** these features carry 0.36% to 0.69% of LightGBM's gain at h = 1 to 3. Not measured for the other models.
- **Not fixed.** A changed feature is a logged trial, and refitting after seeing results is the user's decision. A fix is not expected to change the verdict, but that is an expectation and not a measurement.

## 4. Independent review

A separate read-only agent traced the code before results were read. It found no look-ahead or row misalignment.

| Finding | Action |
|---|---|
| Controls could read PASS with no trades | Checked: 50 of 51 tested; statuses in the report |
| Tabular truncation could not fail | Rewritten: refit with later rows overwritten, 290 predictions per learner, 0 different; a planted leak was detected for all 5 learners |
| Missing action-list split, median, winsorized | Added |
| U2 contains U1, so the spec's "true out-of-universe check" is false, and item f is easier | Spec left frozen; U2-minus-U1 reported |
| Importance and ablation missing | Added |
| `gate.train_mask` drops earlier folds, against its description | Not used, frozen code left as it is |

Disclosed, not changed:
- The development baselines use feature returns and the nearest GARCH horizon, not the frozen baseline path. They are report-only. Validation would use `addendum4_schedules`.
- The time-shift control labels rows with no later return as 0.
- `n_liquid_pairs` is not winsorized.
- `f_rank`'s training label has no 20-name minimum; its trading rule has.
- Shuffling covers all rows, not only training.
- `shuffle=True` in SGD; the spec says fixed order. It is deterministic per seed.
- The validation step was not written, because no spec reached it.

## 5. Limits of "no edge found"

This covers these specs, these features, this cost model and D-1 timing. It is not a proof that no edge exists. In particular, D-1 timing skips the signal day's own close, the cost model is unverified, and market-state features took about 64% of LightGBM's gain, so the tree models lean mostly on market-wide state. All are observations, not grounds for a re-test.
