# PA-44 — Gate v2 addendum 3: pass items, item g option (a), baselines on D-1

| | |
|---|---|
| **Status** | Written. No model built. One reading awaits the user's confirmation (section 2) |
| **Scope** | new `docs/gate_v2_addendum_3.json`, `docs/gate_v2_baselines_d_minus_1.md`; `tradingagents/research/gate2.py`; new `scripts/research_gate2_addendum3.py`; `scripts/research_gate2_harness.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-43](PA_43-gate-v2-addendum-2.md), [PA-42](PA_42-feature-library-v1.md) |
| **Pull request** | branch `research/gate-v2-addendum-3` |
| **Date** | 2026-10-31 |

Research and decision support only, not investment advice. **Cost model unverified; slippage is an ASSUMPTION.** Nothing from 2025-01-01 onward was read. All earlier files are unedited. Trial count: **389** (339 + 50 validation reads).

## 1. The pass

Items a, d, e, f and g. Items b (60% win rate) and c (binomial) are report-only. With item c removed, false pass was at most 0.02% [0.00, 0.11] in 5,000 runs per cell, on random signals ([PA-43](PA_43-gate-v2-addendum-2.md)). That is not evidence about a model selected from many tries.

## 2. Forward correction: needs confirming

The thresholds 0.05, 0.025 and 0.016667 applied to item c. With c report-only, the correction you kept would do nothing. The addendum moves it to item d:

| Forward specs | Item d lower bound, bootstrap percentile |
|---|---|
| 1 | 2.5th (unchanged) |
| 2 | 1.25th |
| 3 | 0.8333rd |

This is my reading, not your instruction. False pass and power at 2 and 3 specs have not been simulated.

## 3. Item g: option (a)

A feature exists in a fold if at least 100 signal dates have it for at least 20 U1 stocks. A market feature needs a value; `basis_spot_index` needs one index.

**Features allowed per fold** (every name is in the addendum):

| Fold | Allowed | What is out, against the fold after it |
|---|---|---|
| 2013-14 | 68 | Participant, delivery, VIX, NIFTY spot, `basis_spot_index` |
| 2015-16 | 106 | `skew_5` and its ranks, `nifty_above_ma_200`, board and results `days_since_last` |
| 2017-18 | 112 | `skew_5_norm` |
| 2019-20 | 113 | `atm_iv_next`, `iv_term_slope`, `iv_term_ratio` |
| 2021-22 | 116 | |
| 2023-24 (validation) | 116 | |

**Which features can go forward:**

| Folds tested | Features | Forward |
|---|---|---|
| 6 | 68 | Yes |
| 5 | 38 | Yes |
| 4 | 6 | Yes |
| 3 | 1: `skew_5_norm` | **No** |
| 2 | 3: `atm_iv_next`, `iv_term_slope`, `iv_term_ratio` | **No** |
| 0 | 2: `board_days_to_next`, `results_days_to_next` | **No** |

112 of 118 input features can go forward.

**"Cannot be the only support" needs no separate test.** With 6 folds, 70% means 5 positive. At least 4 full-set folds leaves at most 2 reduced ones, so at least 3 positive folds are full-set.

**Weak spot in the 100-date test.** Participant and delivery count as existing in 2015-16 on 129 and 128 dates, all from the first quarter of 2015. Item g also needs 100 signal dates in every fold, so a full-set model must signal on at least 100 of those dates. It also means one quarter stands in for a two-year fold. If it counts as reduced instead, these features have 4 full folds, which still passes.

## 4. Baselines on D-1

prev_day, momentum_5d, the GARCH weight and the minimum-move filter now read D-1. Entry and exit timing are unchanged. Full tables: [gate_v2_baselines_d_minus_1.md](gate_v2_baselines_d_minus_1.md). 50 trials logged, one run.

Best baseline, net % per trade at 1.5x costs, all trades:

| h | U1 development, old → D-1 | U1 validation, old → D-1 | U2 development, old → D-1 | U2 validation, old → D-1 |
|---|---|---|---|---|
| 1 | -0.186 → -0.201 | -0.220 → -0.212 | -0.177 → -0.193 | -0.239 → -0.211 |
| 2 | -0.181 → -0.223 | -0.186 → -0.163 | -0.162 → -0.224 | -0.164 → -0.165 |
| 3 | -0.184 → -0.199 | -0.087 → -0.104 | -0.153 → -0.202 | -0.057 → -0.080 |
| 5 | -0.157 → -0.130 | +0.048 → +0.058 | -0.167 → -0.157 | +0.092 → +0.109 |
| 10 | -0.063 → +0.020 | +0.419 → +0.387 | -0.088 → -0.007 | +0.519 → +0.480 |

**Do not read these changes as the value of one session of data.**

- **The trades mostly differ.** A signal is dropped when its session has no one-contract return, the session after an expiry. This quirk has been in the trade build since gate v1. On D-1 the dropped session moves by one, so about 10% of eligible rows change. The one-open-trade rule then shifts each stock's schedule: kept trades differ by 9.8% at h = 1 and 94% to 99.7% at h of 2 or more (development, U1).
- **The noise floor is measured.** Always long and always short read no market data, yet they moved by up to 0.078 points in development and 0.038 in validation. Changes of that size say nothing.
- **Only U1 h = 10 development turned positive,** garch_risk_scaled at +0.020%. That is inside the noise floor.

## 5. Risks and open items

- **Item d percentile by spec count** needs confirming (section 2).
- **Schedule sensitivity affects item e.** A baseline's number moves by up to 0.078 points with its starting schedule, and item e compares a model to a single schedule. No fix is applied here.
- **The expiry quirk removes about 5% of signal sessions.** It is unchanged, because the trade definition is frozen.
- **Fold years** here are by signal date; item g folds by entry year.
- **Feature coverage in validation** was read as non-null counts only, no return or target, and is not logged as a trial.
