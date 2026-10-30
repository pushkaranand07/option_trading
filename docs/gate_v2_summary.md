# Gate v2 in plain English

> **Status:** Frozen 2026-10-30, before the v2 rerun. `docs/gate_v2.json`, hash `ecd52239…`. Gate v1 stays on file, unedited. A change is a new version and a logged event.
> **Scope:** the test any later futures model must pass. It is not a model and says nothing about whether an edge exists.

Research and decision support only, not investment advice. **Cost model unverified; slippage is an ASSUMPTION.**

## What stayed the same

The trade, costs, targets, folds and X_h are v1's. X_h was not re-measured under the new skip rule.

## What changed

| Topic | v1 | v2 |
|---|---|---|
| Skip a trade when | A price / open-interest footprint falls inside it | **Rule A:** NSE's stored corporate-action list has an ex-date after entry, up to exit. The footprint is a diagnostic only (rule B, report only) |
| Actions on the list | n/a | Split, bonus, demerger, consolidation. Demerger and consolidation are a choice beyond the brief |
| Effective trades | Formula with same-date correlation | Distinct signal dates. Minimum 100, target 150 |
| Result | One pass or fail | **Tier 1 "edge present"** and **Tier 2 "meets my 60% target"** |
| Item d interval | 5-date blocks | Calibrated blocks: h = 1 and 2 use 1 date; h = 3, 5 and 10 use 2 dates |
| Forward correction | Bonferroni over all trials | Over pre-registered forward specs only, at most 3. The trial counter keeps counting |

## The two tiers

| Item | Requirement | Tier 1 | Tier 2 |
|---|---|---|---|
| a | At least 100 distinct signal dates (target 150) | Yes | Yes |
| b | Win rate at least 60% | No | Yes |
| c | Exact binomial against the random-direction win rate | Yes | Yes |
| d | Net expectancy and its interval's lower end above 0 | Yes | Yes |
| e | Beats all five baselines | Yes | Yes |
| f | Same sign on U2 | Yes | Yes |
| g | Walk-forward 2013-2024: at least 70% of folds positive, no fold below -X_h%, at least 100 distinct dates in every fold | Yes | Yes |

A Tier 1 pass is never a pass of the 60% gate. "No edge found" is a valid, expected result. A FAIL is never softened or reworded.

## Forward thresholds

One spec: 0.05. Two: 0.025. Three: 0.016667. Tables are in [PA-40](PA_40-gate-v2.md), with the baselines in [gate_v2_baselines.md](gate_v2_baselines.md).

## What the list cannot do

The list covers 2015-02 to 2024-12, missing 2015-01, 2018-12, 2020-05 and 2021-03, with nothing for 2010-2014. Trades in those months are labelled "no action list", and every result is shown with and without them. An action missing from the list stays in the data. The list's announcement date is empty in every stored row, so `known_from` is UNVERIFIED.
