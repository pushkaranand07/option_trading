# PA-25 — Phase 9 exit check: replaying full analyses, and clearer verdict wording for the agents

| | |
|---|---|
| **Status** | In progress — wording fix merged; the 10-date replay is running (results added here when it finishes) |
| **Scope** | `tradingagents/analytics/quant_report.py` (`_validation_lines`), `tradingagents/analytics/replay_check.py`, `scripts/quant_replay.py`, `tests/test_quant_report.py`, `tests/test_replay_check.py` |
| **Related** | [PA-09](PA_09-agent-quant-tool-and-lightgbm.md) (the agent tool), [architecture/16](architecture/16-quant-context-in-agents.md), [features/quant-report](features/quant-report.md) |
| **Pull request** | #27 (branch `quant/phase-9-replay`) |
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

## 5. Results so far

Run 1 (^NSEI 2023-08-10, 10.0 min, rating Overweight): the frozen rule flagged **78 numbers in 35 sentences, 0
validation claims**. Reading every flagged sentence: the flags are numbers from the **other** technical tools (50 /
200-day averages, RSI 52, ATR 161, Bollinger band 19,400) in sentences that also say "regime" — rule 1 is broader than
intended, because it compares those numbers only with the quant tool's output.

A closer look restricted to numbers right after a quant term (GARCH, EWMA, IV, expected move, percentile, regime
probability): **76 numbers, all quant values faithful** (e.g. IV 9.2%, 0th percentile, p calm 1.00, expected move
±1.6–3.6% and ±311 points); the only 3 mismatches were an ATR of 161 and a 150-point stop.

The frozen rule is **not** being changed mid-run. The final report gives both: the frozen rule's verdict, and the
closer look with each remaining flag read and classified.

## 6. Risks and open items

- 9 runs to go at the time of writing (~10 minutes each).
- The rule-1 over-breadth is a design flaw in the check, found by reading its output; a narrower rule would be a new,
  declared version, not a silent edit.
