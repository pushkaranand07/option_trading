# Quant context in the agents

> **Status:** Current. The Phase 9 exit check (10-date replay) was running on 2026-10-24; its result is not recorded yet.
> **Scope:** `tradingagents/analytics/quant_report.py`, `tradingagents/agents/tools.py` (`get_quant_signal_report`),
> `tradingagents/agents/analysts/market_analyst.py`, `tradingagents/agents/managers/portfolio_manager.py`,
> `tradingagents/reporting.py` (`_quant_part`), `tradingagents/analytics/replay_check.py`, `scripts/quant_replay.py`.
> **Last verified against the code:** 2026-10-24

---

## 1. Goal

Give the language-model agents the quant numbers so they argue about evidence instead of guessing it, while making
sure they (a) never invent a number and (b) never present an unvalidated signal as a reason to trade.

## 2. The report text — `quant_report.quant_signal_text(ticker, on)`

Reads only precomputed outputs from the store (regime, volatility forecasts, prices, implied vol) and the trial log.
Nothing is fitted, so a call is fast and cannot change a result.

**Point in time.** Only rows dated **before** the analysis date are used (`_known_rows`): a value about session *d* is
published after *d*'s close and so is known from the open of *d+1*.

**Symbols.** `store_symbol` maps `RELIANCE.NS`, `RELIANCE` or a Yahoo index ticker (`^NSEI`, `^NSEBANK`) to the store's
symbol. Anything outside the universe gets one line saying no quant numbers exist for it.

The text, in order:

| Section | Content |
|---|---|
| Header | "QUANT CONTEXT for <symbol> as known before the open of <date> (research only, not advice)" |
| Regime | NIFTY HMM label as of the last known close, since when, and the three probabilities; plus "Regimes separate future volatility, not direction (return differences by regime were not significant)" |
| Volatility forecasts | GARCH, GJR and EWMA for the next 5, 10 and 21 sessions (annualised), 20-session historical vol, and the note that out of sample GARCH beat historical vol on all 31 symbols and EWMA only narrowly, and that for NIFTY India VIX forecast better than both |
| Expected move | One standard deviation from the GARCH forecast for 5 / 10 / 21 sessions: `garch_h × √(h/252)`, as a percentage and as ±₹ on the last known close; "~2 in 3 moves stay inside" |
| Implied vol | 30-day ATM IV, IV minus the GARCH 21-session forecast ("positive = options priced above forecast volatility"), and IV percentile over the past year (when more than 60 days exist) |
| Validation | Latest trial-log row of each idea (section 3) |
| Survivorship | `universe.SURVIVORSHIP_NOTE` |

Missing inputs give a plain "not available" line rather than an error.

## 3. Validation lines and verdict wording

For each idea's latest run (baselines such as `random` are hidden):

- If the run has a gate verdict, it shows "gates <verdict>" (`approved`, `rejected` or `incomplete`).
- Otherwise the test was judged by its own pre-declared rules, and the recorded verdict is translated:

| Recorded verdict | Shown as |
|---|---|
| `reject`, `rejected` | rejected |
| `keep` | kept as a forecast input (not a trade signal) |
| `pass` | passed its backtest; forward paper trading pending, NOT approved |
| `predictive_check` | predictive check only (not a trade signal) |
| `holdout_fail` | rejected (failed the backward holdout) |

Each line also gives the number of out-of-sample trades and the Sharpe ratio when it is a real number (a missing
Sharpe is left out rather than printed as "nan"). This wording fix landed on 2026-10-24: rule-judged tests had shown
"gates -" and "Sharpe nan".

**Approved-signals rule.** Only ideas whose gate verdict is `approved` are listed under "Approved signals". If there
are none — the case today — the report ends the section with: "NO quant signal has passed the gates. Use the numbers
above as context (volatility, regime), NOT as a reason to buy or sell, and do not describe any of them as validated."
A backtest pass alone is never "approved".

## 4. The agent tool — `get_quant_signal_report`

A LangChain tool in `tradingagents/agents/tools.py`. The symbol (`company_of_interest`) and the run's trade date are
injected from the graph state; the model supplies only `curr_date`, which `as_of` clamps to the run's date so the tool
cannot be asked about the future. It returns `quant_signal_text(symbol, date)`. Its description tells the model to
quote the numbers instead of estimating volatility or regime, and to repeat their validation status.

## 5. Prompt rules

- **Market analyst** (`market_analyst.py`, tool in its tool list): "For NSE F&O stocks, NIFTY and BANKNIFTY, call
  get_quant_signal_report and quote its regime and volatility figures instead of estimating them. Repeat its
  validation status exactly: a quant number that has not passed validation is context about risk, never a reason to
  buy or sell."
- **Portfolio manager** (`portfolio_manager.py`): "Quant figures (market regime, volatility forecasts, implied vol) may
  inform position size and risk, but a quant signal supports a direction only if the quant report lists it under
  'Approved signals'. If an argument rests on an unvalidated quant signal, discount it and say so in the thesis."

## 6. Report section VI

`reporting._quant_part` adds **"VI. Quant Context"** to the saved Markdown and HTML reports (folder `6_quant`, file
`quant.md`, heading "Quant Research Layer"), using the run's trade date. It is left out for tickers outside the
universe, and also when the quant store is unavailable or the text raises: a report is never lost because the quant
store is.

## 7. Phase 9 exit check — `replay_check.py` and `scripts/quant_replay.py`

**Check rules** (`replay_check.py`), fixed and pushed before the first run:

1. **Unsupported numbers.** In every sentence about volatility, expected move, implied vol or regime (`QUANT_WORDS`:
   GARCH, GJR, EWMA, implied vol, IV, expected move, regime, HMM, volatility forecast, historical / realised vol, vol
   percentile), every number must appear in the quant tool's output for that date: a percentage must match one of the
   tool's percentages, any other number any of its numbers — within 0.1, or 1% for large numbers, or equal after
   rounding when the agent wrote a whole number.
2. **Validation claims.** No sentence may call a quant signal or model validated / approved / proven / "passed the
   gates, validation or backtest" unless it is negated ("not validated", "no signal has passed", "rejected", …).

Pass: zero unsupported numbers and zero validation claims across all runs. Every flag is printed with its sentence.

**Runner** (`scripts/quant_replay.py`): 10 full TradingAgents analyses chosen before any run — calm, choppy and event
days across 2022–2026, indices and stocks:

| Ticker | Date | Ticker | Date |
|---|---|---|---|
| ^NSEI | 2023-08-10 | HDFCBANK.NS | 2022-06-14 |
| ^NSEI | 2024-06-05 | INFY.NS | 2026-07-24 |
| ^NSEBANK | 2025-04-08 | TCS.NS | 2026-10-23 |
| RELIANCE.NS | 2026-03-24 | SBIN.NS | 2024-11-25 |
| TATASTEEL.NS | 2022-02-25 | ADANIENT.NS | 2023-01-30 |

Each run uses the LLM set in `.env` (GPT-5 on Azure for this replay, per the tracker), 2 debate rounds and 2 risk
rounds, and its own empty memory log so no run sees another's decision. Text fields checked: the four analyst reports,
investment plan, trader plan, final decision, and the history and judge decision of both debates. Results are saved
under `reports/replay/` (gitignored): one JSON per run, and `summary.md` with every flag and its sentence. Finished runs
are kept, so a rerun resumes.

```powershell
.venv\Scripts\python.exe scripts\quant_replay.py               # run (or resume) the 10 analyses, then check
.venv\Scripts\python.exe scripts\quant_replay.py --check-only  # re-check saved runs, no LLM calls
```

The original plan asked for 50 dates and a direction / size check. The proof plan offered 50 / 10 / skip because of
the LLM cost; the user chose 10 dates and 2 debate rounds (2026-10-24), and the check covers invented numbers and
validation claims. Result and first findings: [PA-25](../PA_25-phase9-replay-and-report-wording.md).

User-facing doc: [../features/quant-report.md](../features/quant-report.md). Related:
[13 — volatility and regime models](13-volatility-and-regime-models.md).
