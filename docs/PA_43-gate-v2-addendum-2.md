# PA-43 — Gate v2 addendum 2: goal, signal timing, item g options

| | |
|---|---|
| **Status** | Goal and timing written. **Item g is open for the user's decision.** No model built |
| **Scope** | new `docs/gate_v2_addendum_2.json`; `tradingagents/research/gate2.py`; new `scripts/research_gate2_addendum2.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-40](PA_40-gate-v2.md), [PA-41](PA_41-gate-v2-addendum.md), [PA-42](PA_42-feature-library-v1.md) |
| **Pull request** | branch `research/gate-v2-addendum-2` |
| **Date** | 2026-10-30 |

Research and decision support only, not investment advice. **Cost model unverified; slippage is an ASSUMPTION.** Nothing from 2025-01-01 onward was read. All earlier files are unedited.

## 1. Goal

Tier 1 is the pass. The 60% win rate is report-only. Tier 2 is removed as a pass condition.

**Open question.** The user's wording names items d, e and f. Items a, c and g are not named, so the addendum keeps gate v2's Tier 1 (a, c, d, e, f, g) until the user says otherwise. Item c matters most: it is a win-rate test, so it conflicts with an expectancy goal.

### What changes in the power table

Fresh seeds, 300 planted runs per cell, one-spec threshold. Cells: 100 / 150 distinct dates. Win is after costs.

| h | Hit | Win | Old Tier 2 (PA-40) | Tier 1, a c d e f g | Without c | a d e f only |
|---|---|---|---|---|---|---|
| 1 | 60% | 52.8% | 0.00 / 0.00 | 0.51 / 0.90 | 0.81 / 0.90 | 0.81 / 0.90 |
| 2 | 60% | 55.1% | 0.00 / 0.00 | 0.76 / 0.98 | 0.97 / 0.98 | 0.97 / 0.98 |
| 3 | 60% | 56.0% | 0.00 / 0.00 | 0.76 / 0.96 | 0.93 / 0.96 | 0.93 / 0.96 |
| 5 | 60% | 57.2% | 0.00 / 0.00 | 0.66 / 0.89 | 0.84 / 0.89 | 0.84 / 0.89 |
| 10 | 60% | 58.0% | 0.04 / 0.01 | 0.66 / 0.85 | 0.75 / 0.85 | 0.75 / 0.85 |
| 1 | 65% | 57.1% | 0.00 / 0.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 2 | 65% | 59.8% | 0.39 / 0.37 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 3 | 65% | 60.7% | 0.81 / 0.90 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 5 | 65% | 61.9% | 0.97 / 0.99 | 0.99 / 1.00 | 0.99 / 1.00 | 0.99 / 1.00 |
| 10 | 65% | 62.6% | 0.93 / 0.99 | 0.94 / 0.98 | 0.94 / 0.98 | 0.94 / 0.98 |
| 3 | 55% | 51.3% | 0.00 / 0.00 | 0.00 / 0.00 | 0.07 / 0.15 | 0.08 / 0.15 |
| 5 | 55% | 52.4% | 0.00 / 0.00 | 0.00 / 0.00 | 0.16 / 0.30 | 0.16 / 0.30 |
| 10 | 55% | 53.3% | 0.00 / 0.00 | 0.00 / 0.01 | 0.18 / 0.26 | 0.18 / 0.26 |

At a 70% or 75% hit, every version is 1.00 to two decimals. At a 55% hit, h = 1 and h = 2 stay at or below 0.02. Old Tier 2 needed about a 65% to 70% hit; Tier 1 is near 1.00 from 65%.

**False pass, 5,000 runs per cell, both nulls, every h, 100 and 150 dates:**

| Version | Result |
|---|---|
| Tier 1, a c d e f g | 0 passes; 0.00% [0.00, 0.07] in every cell |
| Without c | 0.00% except h = 10, zero-mean, 100 dates: 0.02% [0.00, 0.11] |
| a d e f only | 0.00% except h = 10, zero-mean: 0.08% [0.02, 0.20] at 100 dates, 0.02% at 150 |

**Limits of these tables.** Planted signals are symmetric, with wins and losses of similar size. They do not show a low-win, high-payoff model, which is the case item c would block: at 100 dates, one spec, item c needs 53 to 57 wins. The null false-pass rates also stay low because of how little 100 dates and cost-carrying nulls allow; they are not proof for a real selected model.

## 2. Signal timing

Close of D: 15:30 IST. The stored evidence is one manifest: same-evening fetches on 2 dates, at 20:52 and 21:14, and none at or before 15:30. Under the rule, an unverified time counts as D-1.

| Group | Raw fields | Features |
|---|---|---|
| **Public by D's close** | 5 | **8** |
| **Stay at D-1** | 24 | **113** |

**Public by D's close:** calendar date; listed contract expiries; board meeting date, notice timestamp and purpose, when stamped before 15:30.

**Stay at D-1:**

| Source | Fields | Stored evidence |
|---|---|---|
| Futures bhavcopy | open, high, low, close, open_interest, oi_change, contracts, turnover | Fetched 20:52 and 21:14 on 2 dates |
| Option bhavcopy | close, contracts, open_interest, flag_parity, flag_below_intrinsic | Same file |
| Participant file | long and short: index futures, stock futures, index calls, index puts | Same 2 evenings |
| MTO file | deliv_pct | Same 2 evenings |
| Index file | close: NIFTY, BANKNIFTY, India VIX | Same 2 evenings |
| Action files | ex_date | No announcement date stored |

**0 features change.** `features_v1` already follows this rule, so no rebuild is needed.

**Consequence.** A trade entering at the open of D+1 uses market data through D-1, skipping D. Item e's baselines read D's close, so a model is compared with baselines that have one more session of data.

## 3. Item g and missing history: options, not chosen

### Coverage per fold

U1 stocks. Each cell: signal dates with at least 20 stocks filled, then the share of rows filled.

| Fold | Dates | Participant | Delivery | Options ATM | Options skew | India VIX | Price |
|---|---|---|---|---|---|---|---|
| 2013-14 | 493 | 0, 0% | 0, 0% | 448, 60% | 66, 13% | 0, 0% | 492, 100% |
| 2015-16 | 495 | 129, 26% | 128, 26% | 450, 64% | 68, 12% | 485, 98% | 495, 100% |
| 2017-18 | 494 | 245, 50% | 245, 50% | 455, 70% | 103, 13% | 494, 100% | 494, 100% |
| 2019-20 | 497 | 497, 100% | 497, 100% | 485, 77% | 316, 24% | 497, 100% | 497, 100% |
| 2021-22 | 495 | 495, 100% | 495, 100% | 495, 93% | 465, 47% | 495, 100% | 494, 100% |
| 2023-24 (validation) | 495 | 495, 100% | 495, 100% | 495, 98% | 492, 69% | 495, 100% | 494, 100% |

Fold years are by signal date; item g folds by entry year, which can differ by a session at a boundary.

### Folds each option leaves

| Families the model needs | Option (a): folds run | (a): folds with the full model, item g's 100 dates | (a): full model, stricter test | Option (b): folds counted, 100 dates | (b): folds counted, stricter |
|---|---|---|---|---|---|
| Price, OI, ATM options | 6 | 6 | 6 | 6 | 6 |
| Participant or delivery | 6 | 5 | 3 | 5 | 3 |
| Participant, delivery, ATM options | 6 | 5 | 3 | 5 | 3 |
| Options skew | 6 | 4 | 1 | 4 | 1 |
| All four | 6 | 4 | 1 | 4 | 1 |

Each count includes 2023-24, which is validation: subtract 1 for development only. "Stricter" means at least 80% of the fold's dates and 50% of rows filled. Under item g's 100 dates, 2015-16 counts for participant on 129 dates, all from the 2015 first quarter.

### What each option means

| | Option (a) | Option (b) |
|---|---|---|
| Rule | The feature set is fixed per fold, in advance | Folds without a family leave the 70% rule |
| 2013-14, for a participant model | Runs without participant features | Not counted |
| What a pass shows | Each fold tests a different model; older folds never test the model used forward | Fewer folds, but each tests the real model; less history, fewer regimes |
| Main risk | A reduced model's folds can carry the 70% rule | Few folds, and the excluded ones are the oldest |

### Minimum fold count for option (b)

Item g's 70% rule, by folds counted:

| Folds counted | Positive folds needed |
|---|---|
| 6 | 5 |
| 5 | 4 |
| 4 | 3 |
| 3 | 3 |
| 2 | 2 |

Proposal for the user to accept or change: **a minimum of 4 folds, counting validation**. With item g's 100-date test, it allows participant and delivery (5 folds) and all four families (4 folds). With the stricter test, participant and delivery would leave 3 folds and fail. A minimum of 3 would allow them, but then every counted fold must be positive, and one is validation.

## 4. Risks

- **Item c conflicts with the new goal,** unless the user removes it or keeps it knowingly.
- **The timing rule gains nothing today.** Nothing moved. Only a stored publication time at or before 15:30 would move a field.
- **Item e compares unequal data** until baselines and features use the same session.
