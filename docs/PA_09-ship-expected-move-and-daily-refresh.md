# PA-09 — Ship what is validated: expected move in the quant report, scheduled daily refresh

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tradingagents/analytics/quant_report.py`, `scripts/quant_build_store.py`, `scripts/quant_daily_update.cmd` (new), `tests/test_quant_report.py`, `docs/PROGRESS_TRACKER.md` |
| **Related** | [PA-05](PA_05-garch-volatility-and-vrp-condor.md) · [PA-06](PA_06-regime-detection-hmm.md) · [PA-07](PA_07-agent-quant-tool-and-lightgbm.md) · [PA-08](PA_08-relative-strength-model.md) · [the tracker handoff](PROGRESS_TRACKER.md) · [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) · [architecture/16-quant-context-in-agents.md](architecture/16-quant-context-in-agents.md) |
| **Pull request** | #10 (branch `quant/phase-10-ship`); commits `df898d7`, `f089dfe`, `48c6932` |
| **Date** | 2026-10-23 |

---

## 1. Problem

After six tests found no tradable edge from public end-of-day data in the 29-stock universe, the parts that **are**
validated as risk inputs were not yet usable day to day: the GARCH forecast was not turned into something a trader
can act on, and the daily refresh had to be started by hand.

## 2. Root cause / findings

- Validated (PR body): GARCH volatility forecasts (beat historical vol on 31/31 symbols out of sample) and the regime
  model as a risk input (next-month vol 11.5% vs 15.1%, p = 0.026).
- Rejected: MA trend, VRP iron condors (too few trades), LightGBM on price and on NSE derivatives/flow data, relative
  strength (same-day AUC 0.507, −1.2%/yr excess after costs).
- The daily refresh rebuilds the current year, but recomputing every year's implied vol took ~15 min a day.

## 3. Decisions

- **Expected move = price × vol × √(h/252)** — the one-standard-deviation move implied by the GARCH forecast; about
  2 in 3 moves over the horizon stay inside it. Shown for 5, 10 and 21 sessions, in % and rupees, using the last close
  known before the analysis date. Framed as a yardstick for stop distance and option strike width, **not a target**.
- **Schedule:** Windows Task Scheduler, weekdays 19:30 (after NSE publishes its files).
- `quant_build_store.py --years Y` recomputes implied vol only for the rebuilt years and keeps the rest.

## 4. What was built / changed

| File | Change |
|---|---|
| `tradingagents/analytics/quant_report.py` | `_expected_move_lines()` added to the report |
| `scripts/quant_build_store.py` | IV recomputed only for rebuilt years |
| `scripts/quant_daily_update.cmd` (new) | Runs `quant_daily_update.py` with the repo's virtualenv, appends to `~/.tradingagents/cache/quant/daily_update.log`; removal: `schtasks /Delete /TN "TradingAgents quant daily update" /F` |
| `docs/PROGRESS_TRACKER.md` | Relative strength recorded as rejected; "what you can use now" section |

Example from the PR: RELIANCE ±5.0% / ±₹60 over 10 sessions.

## 5. Tests

New test: the expected move scales the forecast by √(h/252) and uses only the last close known before the date.
Full suite **1544 passed, 0 failed** (Windows); ruff clean on the whole repo.

## 6. Results

First end-to-end daily refresh on real data: all 5 steps OK in 6.6 min; `daily_status.json` ok.

## 7. Verification

Daily refresh run end to end on real data (PR test plan). Whether the scheduled 19:30 run itself worked was not
checked in this PR — it did not run (PA-09).

## 8. Risks and open items

- The scheduled task never ran on its first evening (path with spaces, battery defaults, closable console window);
  fixed in PA-09.
- The expected move is a risk measure only; it says nothing about direction.
- Research and decision support only; not investment advice.

## Folded-in change (scheduler fix)

Merged here on 2026-10-26; the full text is in git history.

- **The 19:30 refresh never ran (2026-10-23).** There were three causes:
  - Task Scheduler split the path at the space in `C:\coding\stock market` (0x80070002);
  - the default task settings skipped runs on battery and never caught up a missed start;
  - closing the visible console window killed the run (0xC000013A).

  The fix:
  - the job runs windowless with `pythonw.exe` and a new `--log` option (each step under `python.exe` with
    `CREATE_NO_WINDOW`);
  - the task settings are "start when available" and "run on battery".

  Result: a real scheduled run gave LastTaskResult 0, all 5 steps OK in 9.6 min. The task settings live on the machine,
  not in the repo. The job runs whatever branch is checked out.
