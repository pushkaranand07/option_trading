# PA-39 — Prompt 2: frozen gate v1, targets, validation harness, forward registry, baselines

| | |
|---|---|
| **Status** | Done. No model built |
| **Scope** | new `docs/gate_v1.json`, `docs/gate_v1_summary.md`, `docs/gate_v1_baselines.md`; new `tradingagents/research/gate.py`, `registry.py`; new `scripts/quant_build_base_futures.py`, `scripts/research_gate_harness.py`; `tradingagents/research/loader.py` (`base_futures`); tests `tests/test_research_gate.py` |
| **Related** | [PA-37](PA_37-symbol-map-and-universes.md), [PA-36](PA_36-base-2010-2014.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `research/prompt2-gate` |
| **Date** | 2026-10-30 |

Research and decision support only, not investment advice. **Every result: cost model unverified; slippage is an ASSUMPTION.**

## 1. Problem

Build the pre-registered test any later model must pass: trade definition, costs, targets, gate, walk-forward, self-tests, a forward registry, and a baseline measurement. Daily and multi-day horizons only. No model, no tuning on results, no statement on whether an edge exists.

## 2. Order of work

`gate_v1.json` was committed (`285c1f2`, hash `48379c7a…`) before any harness run. The only earlier measurements were the SD for X_h and the minimum-move check, both on data through 2022-12-31. New data table: `base_futures`, because the entry needs a futures open that `base_fo_summary` lacks. 2,068,418 contract-days 2010-2024, 0 duplicate keys, from local raw files (trial-log event 12).

## 3. Choices beyond the brief, all in the gate file

| Choice | Value | Why |
|---|---|---|
| Contract | Nearest expiry with at least ceil(1.4h) + 4 calendar days left at the signal | One contract outlives the exit, so a roll cannot occur inside a trade |
| Splits and bonuses | A trade is not taken if a price / open-interest footprint falls inside it. Prices are not adjusted | A 1:1 bonus would otherwise look like -50%. Caught 80 of 89 NSE-listed moves in 2015-2022; 115 of 195 footprints there are not on that list. Before 2015: UNVERIFIED |
| Slippage (ASSUMPTION) | 2 bps per fill index, 5 bps stock | No measured historical spread exists |
| Brokerage | Rs 20 against an ASSUMPTION Rs 10 lakh order | No lots may be used |
| Minimum move | Expected move below 2 x round-trip cost at 1.5x | From cost arithmetic. Skips 0.009-0.158% of development trades, so it rarely binds |
| Effective count | N / (1 + (m0 - 1) rho), by signal date | See the risk in section 7 |
| Folds | Entry years 2013-14, 15-16, 17-18, 19-20, 21-22, 23-24 | Long enough that a fold can plausibly hold 100 effective trades |
| Correction | Bonferroni, 0.05 / N | At N = 234: 0.000214 |

## 4. X_h

| h | SD 2010-2022 % | Assumed % | Ratio | X_h % |
|---|---|---|---|---|
| 1 | 2.315 | 1.890 | 1.225 | 0.16 (not rescaled) |
| 2 | 3.354 | 2.673 | 1.255 | 0.28 |
| 3 | 4.099 | 3.273 | 1.252 | 0.34 |
| 5 | 5.326 | 4.226 | 1.260 | 0.44 |
| 10 | 7.586 | 5.976 | 1.269 | 0.63 |

Missed splits remain in this data and raise the SDs (worst gross trade -87.3% at h = 10).

## 5. Self-tests

Series are block-resampled from development trades. 1,000 null runs per horizon; 300 planted runs per cell; 200 per control.

### 6.1 Null calibration: PASS

| h | Full-gate false-pass | Item c alone | Item d alone | Item e alone |
|---|---|---|---|---|
| 1 | 0.0% | 3.1% | 0.0% | 3.6% |
| 2 | 0.0% | 2.3% | 0.1% | 4.8% |
| 3 | 0.0% | 2.6% | 1.0% | 3.0% |
| 5 | 0.0% | 2.9% | 7.9% | 3.6% |
| 10 | 0.0% | 2.8% | 9.7% | 3.7% |

Limit 5%. Item b, the 60% win rate, stopped every null run. **Item d alone exceeds its nominal level at h = 5 and h = 10**: the block bootstrap is too narrow on few dates.

### 6.2 Planted signal: power of the full gate

Direction is right with the stated probability. Cells: pass rate at 100 / 150 effective trades. Realised win rate is lower than the hit rate because of costs.

| h | Hit 55% | 60% | 65% | 70% | 75% |
|---|---|---|---|---|---|
| 1 | 0.00 / 0.00 | 0.00 / 0.01 | 0.09 / 0.10 | 0.61 / 0.66 | 0.94 / 0.96 |
| 2 | 0.00 / 0.00 | 0.01 / 0.01 | 0.29 / 0.26 | 0.76 / 0.76 | 0.88 / 0.91 |
| 3 | 0.00 / 0.00 | 0.02 / 0.04 | 0.34 / 0.33 | 0.71 / 0.72 | 0.80 / 0.87 |
| 5 | 0.00 / 0.00 | 0.08 / 0.05 | 0.30 / 0.36 | 0.54 / 0.63 | 0.81 / 0.74 |
| 10 | 0.01 / 0.01 | 0.06 / 0.13 | 0.24 / 0.41 | 0.36 / 0.59 | 0.45 / 0.73 |

### 6.3 to 6.6

| Test | Result |
|---|---|
| 6.3 Shuffled labels (hit 90% before shuffling) | **PASS**: gate pass rate 0.0% at every h |
| 6.3 Time-shift | **PASS**: 0.0%, 0.0%, 1.0%, 1.0%, 1.5% for h = 1, 2, 3, 5, 10 |
| 6.3 Control: the same signal unshuffled | 100%, 99.5%, 99.5%, 98.5%, 71% |
| 6.4 Look-ahead, truncated at D | **PASS**: synthetic and real store |
| 6.5 Roll gap | **PASS** |
| 6.6 Holdout and live tables | **PASS**: raises, and the attempt is logged |

## 6. Baselines

Measured once on 2010-2024, 50 trials logged. Tables: [gate_v1_baselines.md](gate_v1_baselines.md). A measurement, not a recommendation.

## 7. Risks and open items

- **A defect the self-tests caught.** The first run passed item d on 27% of null runs at h = 10: with no more dates than the block size, the code returned the mean as the lower bound. Fixed to count as a FAIL; the gate file did not change. A second flaw (U2 sampled on mismatched dates) was also fixed. The full-gate false-pass rate was 0.0% before and after.
- **Effective counts depend on the signal's direction.** With mixed long and short signals, same-date returns partly cancel, rho falls and the effective count rises. So a mixed-direction model reaches 100 sooner than an always-long one on the same dates, and "weeks to 100" is optimistic for it. Not changed, because the gate is frozen; for the user to review.
- **U1 cost slippage is one figure per class** across thin and liquid stocks.
- **Missed splits and bonuses stay in the data.**
- **The trial log's Chronos entries have no dates.**
