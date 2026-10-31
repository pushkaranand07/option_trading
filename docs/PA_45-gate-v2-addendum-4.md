# PA-45 — Gate v2 addendum 4: item d by spec count, baselines on 20 schedules

| | |
|---|---|
| **Status** | Done. No model built. **The item e rule is a proposal, not applied** |
| **Scope** | new `docs/gate_v2_addendum_4.json`, `docs/gate_v2_baseline_schedules.md`; `tradingagents/research/gate2.py`; new `scripts/research_gate2_addendum4.py`; `scripts/research_gate2_harness.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-44](PA_44-gate-v2-addendum-3.md), [data catalog](data_catalog.md) |
| **Pull request** | branch `research/gate-v2-addendum-4` |
| **Date** | 2026-10-31 |

Research and decision support only, not investment advice. **Cost model unverified; slippage is an ASSUMPTION.** Nothing from 2025-01-01 onward was read. All earlier files are unedited. Trial count: **1,389** (389 + 1,000 validation reads).

## 1. Item d by forward spec count

5,000 runs per cell on fresh seeds, 2,000 bootstrap draws, exact 95% intervals, development trades, rule A.

**False pass above 5%: none.** Worst item d point estimate: 4.62%. The pass (a, d, e, f, g) false-passed at most 0.02% on random signals, at every spec count.

Item d alone, worst of the four nulls and of 100 and 150 dates:

| h | 1 spec, 2.5th | 2 specs, 1.25th | 3 specs, 0.83rd |
|---|---|---|---|
| 1 | 2.74% [2.31, 3.23] | 1.62% [1.29, 2.01] | 1.22% [0.93, 1.56] |
| 2 | 3.94% [3.42, 4.52] | 2.04% [1.67, 2.47] | 1.50% [1.18, 1.88] |
| 3 | 3.22% [2.75, 3.75] | 1.90% [1.54, 2.32] | 1.50% [1.18, 1.88] |
| 5 | 4.32% [3.77, 4.92] | 2.64% [2.21, 3.12] | 1.92% [1.56, 2.34] |
| 10 | 4.62% [4.05, 5.24] | 2.46% [2.05, 2.93] | 1.84% [1.49, 2.25] |

The upper end of one interval crosses 5%: h = 10, 1 spec. That cell is the existing rule, not a new one.

Power of the pass, 100 / 150 distinct dates, 5,000 runs per cell. Planted hit rate is before costs:

| h | Hit | Win after costs | 1 spec | 2 specs | 3 specs |
|---|---|---|---|---|---|
| 1 | 55% | 48.3% | 0.000 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |
| 1 | 60% | 52.7% | 0.790 / 0.915 | 0.724 / 0.875 | 0.686 / 0.850 |
| 1 | 65% | 57.1% | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 |
| 2 | 55% | 50.6% | 0.001 / 0.000 | 0.000 / 0.000 | 0.000 / 0.000 |
| 2 | 60% | 55.2% | 0.960 / 0.983 | 0.959 / 0.983 | 0.959 / 0.983 |
| 2 | 65% | 59.8% | 0.999 / 1.000 | 0.999 / 1.000 | 0.999 / 1.000 |
| 3 | 55% | 51.4% | 0.085 / 0.141 | 0.058 / 0.094 | 0.044 / 0.075 |
| 3 | 60% | 56.0% | 0.919 / 0.969 | 0.919 / 0.969 | 0.919 / 0.969 |
| 3 | 65% | 60.7% | 0.994 / 0.999 | 0.994 / 0.999 | 0.994 / 0.999 |
| 5 | 55% | 52.4% | 0.165 / 0.250 | 0.121 / 0.202 | 0.105 / 0.174 |
| 5 | 60% | 57.2% | 0.812 / 0.905 | 0.810 / 0.905 | 0.810 / 0.905 |
| 5 | 65% | 61.9% | 0.965 / 0.992 | 0.965 / 0.992 | 0.965 / 0.992 |
| 10 | 55% | 53.1% | 0.187 / 0.287 | 0.153 / 0.245 | 0.136 / 0.224 |
| 10 | 60% | 57.9% | 0.762 / 0.860 | 0.760 / 0.860 | 0.758 / 0.860 |
| 10 | 65% | 62.8% | 0.951 / 0.985 | 0.951 / 0.985 | 0.951 / 0.985 |

At a 70% or 75% hit, every cell is at least 0.994.

## 2. Item e: baselines on 20 schedules

Full tables: [gate_v2_baseline_schedules.md](gate_v2_baseline_schedules.md). Every cell has 20 distinct schedules. Range width, U1, net % per trade, widest baseline:

| h | Development | Validation | 100-session window, median | 100-session window, p90 |
|---|---|---|---|---|
| 1 | 0.005 | 0.014 | 0.078 | 0.148 |
| 2 | 0.010 | 0.033 | 0.170 | 0.289 |
| 3 | 0.041 | 0.053 | 0.311 | 0.689 |
| 5 | 0.062 | 0.210 | 0.905 | 1.432 |
| 10 | 0.248 | 0.386 | 1.976 | 2.769 |

**Proposed, not applied:** a model must beat each baseline's highest net expectancy across 20 schedules built on the same evaluation data.

### What the rule would do to power

1,000 runs per cell, one spec, U1 widths, 100 / 150 dates. In the simulation, each baseline is raised by how far its upper range sits above its mean. A forward test would measure this directly on its own data.

| h | Hit | One schedule | Development width | Validation width | 100-session median | 100-session p90 |
|---|---|---|---|---|---|---|
| 1 | 60% | 0.80 / 0.90 | 0.80 / 0.90 | 0.80 / 0.90 | 0.79 / 0.90 | 0.77 / 0.89 |
| 1 | 65% | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 1 | 70% | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 2 | 60% | 0.96 / 0.98 | 0.96 / 0.98 | 0.96 / 0.98 | 0.90 / 0.96 | 0.84 / 0.93 |
| 2 | 65% | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.99 / 0.99 |
| 2 | 70% | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 3 | 60% | 0.91 / 0.97 | 0.91 / 0.97 | 0.90 / 0.97 | 0.77 / 0.88 | 0.63 / 0.78 |
| 3 | 65% | 0.99 / 1.00 | 0.99 / 1.00 | 0.99 / 1.00 | 0.97 / 0.99 | 0.95 / 0.98 |
| 3 | 70% | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| 5 | 60% | 0.80 / 0.90 | 0.78 / 0.89 | 0.75 / 0.87 | 0.45 / 0.60 | 0.20 / 0.28 |
| 5 | 65% | 0.97 / 0.99 | 0.96 / 0.99 | 0.96 / 0.99 | 0.86 / 0.94 | 0.72 / 0.83 |
| 5 | 70% | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 0.98 / 0.99 | 0.95 / 0.98 |
| 10 | 60% | 0.76 / 0.84 | 0.73 / 0.82 | 0.64 / 0.75 | 0.19 / 0.19 | 0.01 / 0.01 |
| 10 | 65% | 0.95 / 0.99 | 0.94 / 0.98 | 0.92 / 0.97 | 0.66 / 0.80 | 0.21 / 0.28 |
| 10 | 70% | 0.99 / 1.00 | 0.99 / 1.00 | 0.99 / 0.99 | 0.95 / 0.97 | 0.74 / 0.84 |

The 100-session columns are the closest to a forward test. Each is an estimate:

- **They may overstate schedule noise.** In a 100-session window, an offset also removes up to 19 sessions of each symbol's sample. h = 1 has no schedule effect, yet its width is 0.04 to 0.08.
- **A real model's trade path differs from a baseline's,** so this shows the rule's cost, not exact forward power.
- **The rule cannot raise false passes;** it only makes item e harder. It was not re-simulated on nulls.

## 3. Defects in this work

| Defect | Effect | Fix |
|---|---|---|
| Rule offsets in percent were added to expectancies in fractions | The first rule table showed 0.00 power even at a 75% hit | Fixed, tested and re-run. Item d and spec-count results do not use the offsets |
| Trial-log event 25 says 2,000 validation reads | The correct count is 1,000; the trials table was right | Event 26 records the correction |
| The branch was first cut from local `main` before #68 was pulled | Caught before any measurement | Fast-forwarded |

## 4. PROGRESS_TRACKER on main

**Confirmed: the nightly job's tracker step.** Daily update started 2026-10-31 10:12:13; steps `tracker`, exit 0. The file's modification time, 10:23:27, falls in that run. The diff is only the download bar and the last-updated line. It stays uncommitted, as it is not part of this work.

**Two things this surfaced.** The log has no 2026-10-30 19:30 run: the entries are 10-30 11:09 and 10-31 10:12, and the 10:12 run finished with all 8 steps at exit 0. Why the 19:30 run did not appear is UNVERIFIED. That run also started while the checkout was on a research branch, not `main`.
