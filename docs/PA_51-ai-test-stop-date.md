# PA-51 — AI forward test: stop date, version 1.1

| | |
|---|---|
| **Status** | Spec frozen. **No trade has counted.** Questions count from the first weekday session after this is on main |
| **Scope** | new `docs/ai_strategist_test_v1_1.json`; `webapp/ai_test.py`; `tradingagents/research/ai_settle.py`; `scripts/ai_test_settle.py`; `scripts/make_gate_current.py`; `docs/gate_current.md`; `docs/data_catalog.md`; tests |
| **Related** | [PA-49](PA_49-ai-strategist-test.md), [PA-50](PA_50-ai-test-settlement.md), [options](ai_test_options_v1.md) |
| **Date** | 2026-11-01 |

Research and decision support only, not investment advice. **Cost model unverified.**

## Decision

Option (c), the user's. Prompt and model unchanged: hash `a32e251f…`. Spec hash `4a7c59bb…`; version 1 stays on file, unedited, hash `72dd7e97…`.

| Date | What happens |
|---|---|
| 2027-05-01 | Interim check: counts and missed days only. No performance action |
| 2027-11-01 | Stop. Lower bound below 0: retire, and say "no large edge detected". Above 0 and under 500 trades: the user decides in writing to extend or retire, with the trial list shown |

## What I filled in, for the user to check

- **Lower bound exactly 0:** treated as not above 0: retire.
- **Fewer than 50 settled trades at the stop:** no bound is computed, nothing is reported, and the user decides in writing.
- **No performance before the stop.** Version 1 showed results from 50 trades on, which conflicts with "counts only"; version 1.1 removes that.
- **Questions after the stop date do not count.**

## What the stop means

At most about 260 trades by the stop, so the 500-trade pass cannot be reached without an extension. Power near 200 trades: 48% at an edge of 20% of max risk, 92% at 30%.

The settlement script stays locked against real rows: both the interim check and the stop need your approval to run.
