# PA-21 — Phase 9 exit check: replaying full analyses, and clearer verdict wording for the agents

| | |
|---|---|
| **Status** | Done — **no invented quant numbers and no validation claims in 10 full analyses** (on reading every flag); the automatic v1 rule did not pass (too broad) and v2 was declared for future replays |
| **Scope** | `tradingagents/analytics/quant_report.py` (`_validation_lines`), `tradingagents/analytics/replay_check.py`, `scripts/quant_replay.py`, `tests/test_quant_report.py`, `tests/test_replay_check.py` |
| **Related** | [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) (the agent tool), [architecture/16](architecture/16-quant-context-in-agents.md), [features/quant-report](features/quant-report.md) |
| **Pull request** | #27 (branch `quant/phase-9-replay`, the check and the wording fix); results and check v2: branch `quant/phase-9-result` |
| **Date** | 2026-10-24 |

## 1. Problem

Phase 9's exit gate: when the agents quote the quant layer's numbers (volatility forecasts, expected move, implied
vol, regime), are they faithful, and does any agent present a quant signal as validated? The user chose 10 dates
instead of 50, 2 debate rounds, and a key check first (user). The LLM is GPT-5 on Azure OpenAI (from `.env`).

## 2. Findings before the replay

**The agents' input was misleading.** In the validation list of `quant_signal_text`, tests judged by their own
pre-declared rules (results fly, Chronos, move size, the holdout) recorded only a verdict, so the agents saw
`gates -` and `Sharpe nan` — readable as "not judged yet" — and the `random` baseline appeared as a signal. Fixed
before any replay run:

| Recorded | Agents now see |
|---|---|
| `verdict = reject` | rejected |
| `verdict = holdout_fail` | rejected (failed the backward holdout) |
| `verdict = predictive_check` | predictive check only (not a trade signal) |
| `verdict = keep` | kept as a forecast input (not a trade signal) |
| `verdict = pass` | passed its backtest; forward paper trading pending, NOT approved |
| idea `random` | hidden (a baseline) |

"NO quant signal has passed the gates" still appears unless a gate verdict is `approved`.

## 3. Decisions — check rules fixed and pushed before the first run

`replay_check.py`:
1. Every number in a sentence about volatility, expected move, implied vol or regime must match the quant tool's output
   for that date: a percentage only a percentage; within 0.1 (1% for large numbers), or equal after rounding when the
   agent wrote a whole number.
2. No sentence may call a quant signal or model validated / approved / proven unless negated.

Pass = zero unsupported numbers and zero validation claims; every flag printed with its sentence. Runs (chosen before
any run): ^NSEI 2023-08-10 and 2024-06-05, ^NSEBANK 2025-04-08, RELIANCE 2026-03-24, HDFCBANK 2022-06-14, INFY
2026-07-24, TCS 2026-10-23, SBIN 2024-11-25, TATASTEEL 2022-02-25, ADANIENT 2023-01-30. Each run gets its own empty
memory log (no run sees another's decision; the user's real memory log is untouched); outputs in `reports/replay/`
(gitignored).

## 4. Tests

Faithful quotes with agent rounding pass; an invented 31.5% is caught; a percentage cannot borrow a trade count
(19 trades ≠ IV 19%); decimals must be close but whole numbers may round; validation claims flagged unless negated;
sentences without quant words are not checked. Verdict wording: rule-judged tests show their verdict, baselines hidden,
a backtest pass is not an approval.

## 5. Results

### 5.1 The ten runs (GPT-5 on Azure, 2 debate and 2 risk rounds)

| Run | Minutes | Rating | v1 flags (numbers / claims) | v2 flags (numbers / claims) |
|---|---|---|---|---|
| ^NSEI 2023-08-10 | 10.0 | Overweight | 78 / 0 | 4 / 0 |
| ^NSEI 2024-06-05 | 10.1 | Underweight | 35 / 1 | 0 / 0 |
| ^NSEBANK 2025-04-08 | 10.2 | Overweight | 39 / 0 | 1 / 0 |
| RELIANCE 2026-03-24 | 10.3 | Underweight | 103 / 0 | 11 / 0 |
| HDFCBANK 2022-06-14 | 10.6 | Overweight | 43 / 0 | 1 / 0 |
| INFY 2026-07-24 | 9.1 | Underweight | 97 / 0 | 8 / 0 |
| TCS 2026-10-23 | 10.3 | Overweight | 42 / 0 | 1 / 0 |
| SBIN 2024-11-25 | 9.8 | Overweight | 46 / 0 | 3 / 0 |
| TATASTEEL 2022-02-25 | 8.9 | Hold | 107 / 0 | 6 / 0 |
| ADANIENT 2023-01-30 | 12.2 | Sell | 53 / 1 | 5 / 0 |
| **Total** | 101.5 (12:15 → 13:57) | | **643 / 2** | **40 / 0** |

(The ratings are reported, not judged: this check is about quoting, not about whether a call was right.)

### 5.2 The frozen rule (v1): not passed

643 unsupported numbers and 2 validation claims in 1,259 sentences. Reading them: rule 1 tests every number in any
sentence that mentions volatility or regime, including the **other** tools' numbers (moving averages, RSI, ATR,
Bollinger bands, support levels, the agents' own strike suggestions), against the quant tool only. Both "claims" were
misfires: "a focused, **cross-validated** read of ^NSEI" and "a **proven** incubator model" (Adani's business).

### 5.3 Reading every flag: passed

Numbers in the clause right after a quant term: **799** across the 10 runs. The 40 that v2 flags, each read:

| Kind | Count | Examples |
|---|---|---|
| Other tools' technical numbers | 19 | ATR 161, 50 / 200-day averages, Bollinger 1,350.84, support 93.59, stop 769.8 |
| The agents' own trade suggestions | 18 | "sell 1100C / buy 1125C", "Feb 23 3300P / 2900P", "30–45 day covered calls at 1470–1500" |
| Faithful paraphrase | 3 | "IV in the 80th+ percentile" (tool: 83%) |
| **Invented or wrong quant number** | **0** | — |

Examples of exact quoting: INFY "IV is 9.9% above 21-day GARCH and in the 92nd percentile" (tool: +9.9%, 92%);
ADANIENT "±14.8% over 5 sessions, ±19.4% over 10, ±24.8% over 21" (tool: the same); NIFTY 2023 "low IV (30d IV 9.2%,
0th percentile)". Agent rounding such as "±20% two-week expected moves" for ±19.4% occurs and is acceptable.

**Verdict: Phase 9 exit gate passed on reading every flag** — the agents quote the quant layer faithfully and never
present a quant signal as validated. The automatic v1 rule's "not passed" is recorded as it is.

### 5.4 Check v2 (declared after this replay, for future ones)

`replay_check.check_v2`: only numbers in the clause right after a quant term (never across a sentence end, never
cutting a number), whole numbers may differ by less than 1; claims need a quant-specific subject and skip
"cross-validated". `python scripts/quant_replay.py --check-only --rule v2` (default) or `--rule v1`. Tests built from
this replay's real false alarms; an invented GARCH number and a real "validated" claim are still caught. v2 still flags
the agents' own strike suggestions near the word "IV", so flags are still read, not just counted.

## 6. Risks and open items

- Ten dates, one LLM (GPT-5) and one prompt version: a change of model or prompts needs a new replay.
- v2 was written after seeing this replay's output; it has not yet judged an unseen replay.
