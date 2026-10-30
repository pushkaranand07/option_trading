# PA-40 — Gate v2: action-list skip rule, distinct dates, two tiers, calibrated item d

| | |
|---|---|
| **Status** | Done. No model built |
| **Scope** | new `docs/gate_v2.json`, `docs/gate_v2_summary.md`, `docs/gate_v2_baselines.md`; new `tradingagents/research/gate2.py`; new `scripts/quant_build_base_actions.py`, `scripts/quant_action_diagnostics.py`, `scripts/research_gate2_harness.py`, `scripts/research_gate2_reachability.py`; `tradingagents/research/loader.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-39](PA_39-gate-v1-and-harness.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `research/gate-v2` |
| **Date** | 2026-10-30 |

Research and decision support only, not investment advice. **Every result: cost model unverified; slippage is an ASSUMPTION.** Nothing from 2025-01-01 onward was read.

## 1. Order of work

`gate_v2.json` was committed (`5831afe`, hash `ecd52239…`) before the rerun and logged as a gate-version change. Block lengths were calibrated before the freeze. `gate_v1.json` was not edited. The rerun used development and validation only. Validation has now been seen for baselines, and that is logged; it is still used once per frozen model spec.

## 2. Skip rule diagnostics, development 2010-2022, U1

The list has 926 rows: bonus 422, split 400, demerger 103, consolidation 1. It covers 116 monthly files from 2015-02 to 2024-12, missing 2015-01, 2018-12, 2020-05 and 2021-03, with none for 2010-2014. The announcement date is empty in all 22,323 stored rows, so `known_from` is UNVERIFIED.

**The -87% trade:** ADANIENT, signal 2015-05-25, entry 2015-05-26 at 788.25, exit 2015-06-08 at 100.05, gross -87.3%. The close fell from 634.40 on 06-02 to 110.30 on 06-03. The detector missed it. **Corrected in [PA-41](PA_41-gate-v2-addendum.md):** the action files do list a Scheme Of Arrangement on 03-Jun-2015, which rule A's kinds leave out, and open interest was reset that day.

**The 115 flags:** all 115 sit in development. 7 have a rule A action within 3 days; 108 have none. Counting every subject, 13 and 102 ([PA-41](PA_41-gate-v2-addendum.md)).

| h | Trades | With list | Removed by list | Removed by detector | Left under A, flagged | Extreme under A | Of those, no list | Extreme under B | Flagged, not listed | Their positive share | Their mean gross % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 299,799 | 192,918 | 0 | 0 | 0 | 6 | 1 | 6 | 0 | n/a | n/a |
| 2 | 299,394 | 192,446 | 61 | 150 | 96 | 32 | 17 | 16 | 67 | 32.8% | -5.45 |
| 3 | 299,070 | 191,898 | 122 | 296 | 188 | 57 | 33 | 20 | 131 | 30.5% | -4.05 |
| 5 | 298,595 | 190,903 | 242 | 583 | 367 | 132 | 69 | 36 | 254 | 30.7% | -6.06 |
| 10 | 297,144 | 188,320 | 542 | 1,268 | 782 | 445 | 166 | 182 | 531 | 29.9% | -9.39 |

Extreme: gross at or below -40%, or at or above +66.7%. The detector removes mostly losers, so rule B can flatter results, which is one more reason the gate uses rule A. Rule A keeps those unlisted losses in.

## 3. Item d calibration

Longer blocks made the false pass worse, so the lowest worst case was chosen per horizon.

| h | Block (dates) | Worst case, calibration seeds | Worst case, fresh seeds | Limit 5% | Nominal 2.5% |
|---|---|---|---|---|---|
| 1 | 1 | 3.2% | 3.6% | Met | Above |
| 2 | 1 | 3.8% | 4.6% | Met | Above |
| 3 | 2 | 3.9% | 4.6% | Met | Above |
| 5 | 2 | 4.5% | **5.7%** | **Not met** | Above |
| 10 | 2 | 4.2% | 5.0% | Met, at the limit | Above |

**Item d at h = 5 exceeds the limit on fresh seeds:** 5.7% on the regime null at 150 dates. With 1,000 runs the standard error is about 0.7 points, so this may be noise, but it is the honest reading of the requirement. The gate stays frozen; re-picking a block from these seeds would be tuning on the test.

## 4. Self-tests

Series are block-resampled from development trades under rule A. 1,000 null runs per horizon; 300 planted runs per cell; 200 per control.

### 6.1 Null calibration

Cells show 100 / 150 distinct dates on the zero-mean null, the harder of the two. On the cost-carrying null every Tier 1, Tier 2 and item d rate is 0.0%. "Tier 1" is Tier 2 with item b removed.

| h | v1 full gate | v2 Tier 1 | v2 Tier 2 | v1 item d alone | v2 item d alone | v2 item d, fresh seeds, worst null |
|---|---|---|---|---|---|---|
| 1 | 0.0% | 0.0 / 0.0% | 0.0 / 0.0% | 0.0% | 3.6 / 3.8% | 3.6 / 3.3% |
| 2 | 0.0% | 0.0 / 0.0% | 0.0 / 0.0% | 0.1% | 2.4 / 2.8% | 4.6 / 4.2% |
| 3 | 0.0% | 0.0 / 0.0% | 0.0 / 0.0% | 1.0% | 4.2 / 3.6% | 4.6 / 3.5% |
| 5 | 0.0% | 0.0 / 0.0% | 0.0 / 0.0% | 7.9% | 4.5 / 5.1% | 4.0 / 5.7% |
| 10 | 0.0% | 0.0 / 0.0% | 0.0 / 0.0% | 9.7% | 3.4 / 3.7% | 5.0 / 4.5% |

v1 ran one null, the cost-carrying kind, so its item d column is not like for like. v2 raises item d's rate at h = 1, 2 and 3 because the blocks are shorter and the null is harder; it lowers it at h = 5 and 10.

Tier 1 reaches 0.0% partly because item g passes only about 11% of zero-mean runs and item c almost none. Item c alone is 7.1% at h = 1 with 150 dates on the zero-mean null, because that null's uncosted wins are compared with a costed win rate. It did not produce a Tier 1 pass.

### 6.2 Planted signal: power

Direction is right with the stated hit rate, before costs. Cells: pass rate at 100 / 150 distinct dates, at the one-spec threshold. Power at the two-spec and three-spec thresholds was not simulated.

**Tier 1, "edge present"**

| h | Hit 55% | 60% | 65% | 70% | 75% |
|---|---|---|---|---|---|
| 1 | 0.00 / 0.00 | 0.52 / 0.92 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 2 | 0.00 / 0.00 | 0.75 / 0.98 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 3 | 0.00 / 0.00 | 0.74 / 0.98 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 5 | 0.00 / 0.00 | 0.61 / 0.93 | 0.97 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 10 | 0.00 / 0.01 | 0.62 / 0.87 | 0.95 / 0.99 | 1.00 / 1.00 | 1.00 / 1.00 |

**Tier 2, "meets my 60% target"**

| h | Hit 55% | 60% | 65% | 70% | 75% |
|---|---|---|---|---|---|
| 1 | 0.00 / 0.00 | 0.00 / 0.00 | 0.00 / 0.00 | 0.96 / 0.99 | 1.00 / 1.00 |
| 2 | 0.00 / 0.00 | 0.00 / 0.00 | 0.39 / 0.37 | 1.00 / 1.00 | 1.00 / 1.00 |
| 3 | 0.00 / 0.00 | 0.00 / 0.00 | 0.81 / 0.90 | 1.00 / 1.00 | 1.00 / 1.00 |
| 5 | 0.00 / 0.00 | 0.00 / 0.00 | 0.97 / 0.99 | 1.00 / 1.00 | 1.00 / 1.00 |
| 10 | 0.00 / 0.00 | 0.04 / 0.01 | 0.93 / 0.99 | 1.00 / 1.00 | 1.00 / 1.00 |

**Win rate after costs, for a planted hit rate**

| h | 55% | 60% | 65% | 70% | 75% |
|---|---|---|---|---|---|
| 1 | 48.3% | 52.8% | 57.1% | 61.5% | 65.9% |
| 2 | 50.5% | 55.1% | 59.8% | 64.3% | 69.0% |
| 3 | 51.3% | 56.1% | 60.7% | 65.4% | 70.1% |
| 5 | 52.4% | 57.2% | 61.9% | 66.7% | 71.4% |
| 10 | 53.1% | 57.9% | 62.8% | 67.6% | 72.4% |

**v1 full gate, same cells, for comparison**

| h | Hit 55% | 60% | 65% | 70% | 75% |
|---|---|---|---|---|---|
| 1 | 0.00 / 0.00 | 0.00 / 0.01 | 0.09 / 0.10 | 0.61 / 0.66 | 0.94 / 0.96 |
| 2 | 0.00 / 0.00 | 0.01 / 0.01 | 0.29 / 0.26 | 0.76 / 0.76 | 0.88 / 0.91 |
| 3 | 0.00 / 0.00 | 0.02 / 0.04 | 0.34 / 0.33 | 0.71 / 0.72 | 0.80 / 0.87 |
| 5 | 0.00 / 0.00 | 0.08 / 0.05 | 0.30 / 0.36 | 0.54 / 0.63 | 0.81 / 0.74 |
| 10 | 0.01 / 0.01 | 0.06 / 0.13 | 0.24 / 0.41 | 0.36 / 0.59 | 0.45 / 0.73 |

### 6.3 to 6.6

| Test | v1 | v2 |
|---|---|---|
| 6.3 Shuffled labels | 0.0% at every h | Tier 1 and Tier 2 0.0% at every h |
| 6.3 Time-shift | 0.0, 0.0, 1.0, 1.0, 1.5% | Tier 1: 0.0, 0.0, 0.0, 2.0, 6.0%. Tier 2: 0.0% at every h. **See below** |
| 6.3 Control: the same signal unshuffled | 100, 99.5, 99.5, 98.5, 71% | Tier 1 and Tier 2 100% at every h |
| 6.4 Look-ahead, truncated at D | Pass | Pass (test suite, real store) |
| 6.5 Roll gap | Pass | Pass (test suite, real store) |
| 6.6 Holdout and live tables | Pass | Pass (test suite, real store) |

**Time-shift at h = 10 is 6.0%, above 5%.** The control moves direction by 3 dates, and a 3-date shift still overlaps a 5-day or 10-day return, so the shifted signal keeps real information: its mean win rate is 51.9% at h = 5 and 53.5% at h = 10. The control is weak at long horizons rather than showing a gate leak, but a shift of at least h was not run, so that reading is not confirmed.

## 5. Baselines

Trial count 334 (234 + 100 logged here); Bonferroni across all trials 0.000150, for the record only. Tables: [gate_v2_baselines.md](gate_v2_baselines.md).

Best baseline at 1.5x costs, U1, % per trade. Each cell shows rule A / rule B.

| h | Development, all | Development, with list | Validation (all trades have a list) |
|---|---|---|---|
| 1 | -0.186 / -0.186 | -0.199 / -0.199 | -0.220 / -0.220 |
| 2 | -0.181 / -0.186 | -0.219 / -0.221 | -0.186 / -0.183 |
| 3 | -0.184 / -0.194 | -0.177 / -0.172 | -0.087 / -0.084 |
| 5 | -0.157 / -0.143 | -0.166 / -0.180 | +0.048 / +0.054 |
| 10 | -0.063 / -0.029 | +0.051 / -0.022 | +0.419 / +0.421 |

- **Item e is harder than the development numbers suggest at long horizons.** In validation at h = 10, always long makes +0.419% on U1 and +0.519% on U2. That is a rising 2023-2024 market, not an edge.
- **Rule choice flips one sign.** At h = 10, development, with list, U1 5-day momentum is +0.051% under A and -0.022% under B. No result in development should rest on a margin that size.
- 16 rule-A cells are positive at 1.5x, counting each validation cell under both "all" and "with list". 14 are in validation; the other two are h = 10 momentum, with list, on U1 and U2.

## 6. Forward correction

Null win rate per h: development, U1, rule A, 1.5x, random direction. It will differ on forward data. Each cell: wins needed at 100 / 150 dates; dates needed at a 60% win rate; dates needed at 55%.

| h | Null win rate | 1 spec, p < 0.05 | 2 specs, p < 0.025 | 3 specs, p < 0.016667 |
|---|---|---|---|---|
| 1 | 43.9% | 53 / 77; 31; 61 | 55 / 79; 41; 81 | 56 / 80; 46; 101 |
| 2 | 46.0% | 55 / 80; 36; 90 | 57 / 82; 51; 121 | 58 / 83; 61; 141 |
| 3 | 46.7% | 56 / 81; 41; 101 | 57 / 83; 56; 141 | 58 / 84; 66; 170 |
| 5 | 47.6% | 57 / 83; 46; 130 | 58 / 84; 66; 181 | 59 / 85; 76; 210 |
| 10 | 48.3% | 57 / 83; 51; 161 | 59 / 85; 76; 221 | 60 / 86; 86; 261 |

## 7. Earliest forward dates

From 2026-10-27, at the highest signal-date rate measured on any baseline, universe and period.

| h | Dates per session | 100 dates | 150 dates |
|---|---|---|---|
| 1 | 0.998 | 2027-03-19 | 2027-05-28 |
| 2 | 0.990 | 2027-03-22 | 2027-05-31 |
| 3 | 0.888 | 2027-04-06 | 2027-06-23 |
| 5 | 0.926 | 2027-03-30 | 2027-06-14 |
| 10 | 0.855 | 2027-04-12 | 2027-07-02 |
| Absolute bound, a date every session | 1.000 | 2027-03-18 | 2027-05-27 |

These are earliest bounds. No 2027 holiday list is stored, so every 2027 weekday counts as a session, and the real dates are later: **2027 sessions UNVERIFIED**. They also ignore the h sessions until the last trade closes, and any collection gaps. A model that signals less often takes longer.

## 8. Risks and open items

- **v1 self-test omission.** The v1 synthetic item e used 4 of the 5 baselines and left out GARCH. v2 uses all five, so v1's item e rates were not a test of the full item.
- **A choice beyond the brief.** Rule A also skips demerger and consolidation dates, as they change the price the same way. You asked for split and bonus.
- **Item d at h = 5 misses the 5% limit on fresh seeds; time-shift at h = 10 is above 5%.** Sections 3 and 4.
- **Item d stays above its nominal 2.5%** at every h on zero-mean nulls.
- **Missed events stay in rule A.** Section 2. Before 2015 there is no list at all.
- **X_h was not re-measured** under rule A, and missed events still inflate it.
- **Power at the two-spec and three-spec thresholds was not simulated.**
- **Slippage is one figure per class** across thin and liquid stocks.
