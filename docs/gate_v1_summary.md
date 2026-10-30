# Gate v1 in plain English

> **Status:** Frozen 2026-10-30, before any harness run. `docs/gate_v1.json`, hash `48379c7a…`. A change is a new version and a logged trial.
> **Scope:** the test any later futures model must pass. It is not a model and says nothing about whether an edge exists.

Research and decision support only, not investment advice.

## The trade

After Monday's close, using only what was public by then, a model says long, short or nothing. It enters at Tuesday's open and exits at a close h sessions after the signal, for h of 1, 2, 3, 5 or 10. There are no stops or targets. It holds one contract throughout, chosen so it outlives the exit, so a roll can never appear as profit. One trade per underlying at a time; signals during an open trade are ignored. A win means net return strictly above zero.

## The costs

The repo's futures charges (**cost model unverified**), plus **assumed** slippage of 2 bps per fill on index futures and 5 bps on stock futures, and Rs 20 brokerage against an assumed Rs 10 lakh order. That comes to 0.10% (index) and 0.16% (stock) per round trip. Results are reported at 1x, 1.5x and 2x; the gate uses 1.5x.

## The gate: all seven must pass, on the forward holdout from 2026-10-27

| Item | Requirement |
|---|---|
| a | At least 100 effective trades (target 150). Same-date signals count less than their raw number |
| b | Win rate at least 60% |
| c | Beats the same trades in a random direction: exact binomial p < 0.05, against that baseline's measured win rate, not 50% |
| d | Net expectancy above 0, with the lower end of a 95% interval above 0 |
| e | Beats always long, always short, previous-day sign, 5-day momentum sign and a GARCH risk-scaled long |
| f | Same sign of result on U2 |
| g | Walk-forward 2013-2024: positive in at least 70% of folds; no fold below -X_h% per trade; at least 100 effective trades in every fold |

X_h: h=1 0.16, h=2 0.28, h=3 0.34, h=5 0.44, h=10 0.63. These are your formula, rescaled at h = 2, 3, 5 and 10 because measured 2010-2022 volatility was over 25% above the 30% assumption.

"No edge found" is a valid, expected result. A FAIL is never softened or reworded.

## The forward registry

A signal is written to a hash-chained file before the entry session opens. A trade not in it before entry does not count. A missed day is recorded as missed and can never be filled in.
