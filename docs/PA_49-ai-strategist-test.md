# PA-49 — Honest Plan tab labels and a pre-registered forward test for the AI strategist

| | |
|---|---|
| **Status** | Done. No trade has counted yet. Test not started: it starts on the first session after this is on main |
| **Scope** | `webapp/static/app.js`, `style.css`, `webapp/strategist.py`; new `webapp/ai_test.py`, `docs/ai_strategist_test_v1.json`, `scripts/research_ai_test_power.py`; `tradingagents/research/registry.py`; `docs/data_catalog.md`; tests |
| **Related** | [PA-48](PA_48-model-suite-v1-refit.md), [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) |
| **Date** | 2026-10-31 |

Research and decision support only, not investment advice. **Cost model unverified.**

## 1. Labels

- Every AI trade and ranked ticket shows **UNTESTED, no evidence of edge**.
- **The 0-100 score is off the screen,** replaced by the plain list of inputs. Reason: its inputs (trend, PCR, OI) showed no edge in the LightGBM test (same-day AUC 0.502, [PA-07](PA_07-agent-quant-tool-and-lightgbm.md)) and in model suite v1 ([PA-48](PA_48-model-suite-v1-refit.md)).
- **The score still sets the rank order** behind the screen, and old trade rows keep their stored score. The rule-based baseline needs that order; the page says the order comes from a rule with no edge.
- **Cost model unverified** appears wherever P&L or charges are shown.

## 2. UI feature freeze

No new UI features until the test has a verdict. Bug fixes are allowed.

## 3. The test

Spec: [ai_strategist_test_v1.json](ai_strategist_test_v1.json), hash `72dd7e97…`. Prompt hash `a32e251f…`, model azure / gpt-5, reasoning medium.

**Power, share of runs passing** (1,000 per cell, edge as a share of max risk per trade):

| Edge | 50 | 100 | 200 | 300 | 500 | 1,000 | 2,000 |
|---|---|---|---|---|---|---|---|
| 0% | 0.01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 5% | 0.02 | 0.02 | 0.02 | 0.03 | 0.03 | 0.05 | 0.06 |
| 10% | 0.04 | 0.05 | 0.09 | 0.12 | 0.19 | 0.32 | 0.66 |
| 15% | 0.06 | 0.12 | 0.20 | 0.35 | 0.55 | 0.84 | 0.99 |
| 20% | 0.13 | 0.22 | 0.48 | 0.66 | 0.85 | 0.99 | 1.00 |
| 30% | 0.32 | 0.59 | 0.92 | 0.97 | 1.00 | 1.00 | 1.00 |

**The verdict comes at 500 settled trades, once.** At one trade a session, that is about 2 years. It detects about 20% of max risk per trade reliably, and it will likely miss smaller edges. Fifty trades detect almost nothing: 13% power even at a 20% edge.

## 4. Existing records

None of the 5 app trades or the 1 paper position counts: none was registered before entry. The paper position is also a different, rule-based strategy. Their performance was not analysed.

## 5. Limits

- **Paper entries at quoted prices,** not real fills.
- **Hold to expiry ignores the AI's target and stop,** so this tests its direction and structure, not its full plan.
- **The test needs a question every session.** Days without one are recorded as missed; if many are missed, the verdict arrives later.
- **The registry and chains are local, under the gitignored `reports/`,** so they are not backed up by git.
- **The settlement and baseline script is not built;** it needs real rows.
- **Hook only fires when `start` runs:** the Plan tab's Ask flow. A model behind the same deployment name can change undetected.
- **Power uses closing prices from 2019-2022 and an assumed structure mix.**
