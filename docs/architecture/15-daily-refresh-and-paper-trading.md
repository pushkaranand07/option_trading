# Daily refresh and paper trading

> **Status:** Current.
> **Scope:** `scripts/quant_daily_update.py`, `scripts/quant_daily_update.cmd`, `scripts/quant_paper.py`,
> `tradingagents/analytics/paper.py`, `tradingagents/analytics/paper_strategies.py`.
> **Last verified against the code:** 2026-10-24

Research only, not investment advice.

---

## 1. The daily job — `quant_daily_update.py`

Runs after the close, once NSE has published the day's files (after about 19:00 IST). Each step is a separate script
run as a child process with the console `python.exe` next to the running interpreter, `-W ignore`, the repository root
as working directory, and no window (`CREATE_NO_WINDOW`).

| # | Step | Command | What it refreshes |
|---|---|---|---|
| 1 | `download` | `scripts/quant_backfill.py --start <today−10 days> --end <end> --retry-missing` | Last 10 days of NSE files, re-checking days marked missing |
| 2 | `store` | `scripts/quant_build_store.py --years <this year>` | This year's store, prices, quality report and 30-day IV |
| 3 | `volatility` | `scripts/quant_vol_forecasts.py` | GARCH / GJR / EGARCH / hist / EWMA forecasts |
| 4 | `regime` | `scripts/quant_regime.py` | Regime probabilities and labels |
| 5 | `tracker` | `scripts/update_progress.py` | Progress bars in `docs/PROGRESS_TRACKER.md` |
| 6 | `market_map` | `scripts/market_map.py` | `reports/market_map/india-market-map.html` ([17](17-market-map.md)) |
| 7 | `paper` | `scripts/quant_paper.py` | Forward paper-trading ledger (section 4) |
| 8 | `quotes` | `scripts/quant_option_quotes.py` | NSE option bid/ask snapshot |

`<end>` is today when the job starts at 19:00 or later, otherwise yesterday.

**First failure stops the run.** `run_steps` stops at the first non-zero exit code, because later steps would build on
stale or half-built data. Option quotes run last so an NSE hiccup there never blocks paper trading.

**Status file.** After a real run (not `--dry-run`) the job writes `<data_cache_dir>/quant/daily_status.json`:

```json
{"started": "...", "finished": "...", "ok": true,
 "steps": [{"step": "download", "exit_code": 0, "seconds": 12.3}, ...]}
```

`ok` is true only when all 8 steps ran and each exited 0. The job itself exits 0 or 1 accordingly.

**Logging.** `--log <file>` appends everything, including each step's output, to that file, with a timestamp header per
run. This is required under `pythonw.exe`, which has no console.

```powershell
.venv\Scripts\python.exe scripts\quant_daily_update.py --dry-run   # print the 8 steps only
.venv\Scripts\python.exe scripts\quant_daily_update.py             # run them
```

## 2. Windows Task Scheduler

The job runs **weekdays at 19:30** as the scheduled task **`TradingAgents quant daily update`**. The task runs:

```
.venv\Scripts\pythonw.exe -W ignore scripts\quant_daily_update.py --log %USERPROFILE%\.tradingagents\cache\quant\daily_update.log
```

`scripts/quant_daily_update.cmd` runs the same command by hand (it changes to the repository root first).

Why it is set up this way (PR #12, "Fix the scheduled daily refresh (it never ran)"):

| Problem found | Fix |
|---|---|
| The repository path contains a space; the task ran `C:\coding\stock` (error 0x80070002) | Executable and arguments set separately, with a working directory |
| Default settings skipped runs on battery and never caught up a missed start | Task settings: start when available, run on battery |
| A visible console window could be closed mid-run (0xC000013A) | Windowless `pythonw.exe` with `--log`; steps start with `CREATE_NO_WINDOW` |

The exact command used to register the task is not recorded in the repository. One way to recreate it with those
settings, from the repository root in PowerShell:

```powershell
$repo = (Get-Location).Path
$action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" `
  -Argument "-W ignore scripts\quant_daily_update.py --log `"$env:USERPROFILE\.tradingagents\cache\quant\daily_update.log`"" `
  -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 19:30
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName "TradingAgents quant daily update" -Action $action -Trigger $trigger -Settings $settings
```

**The job runs whatever branch is checked out.** Keep `main` checked out when not working on a branch. Operations
(checking it ran, re-running, removing it): [../development/scheduled-job-operations.md](../development/scheduled-job-operations.md).

## 3. Paper trading — the idea

Stage 3 of [../plans/PROOF_PLAN.md](../plans/PROOF_PLAN.md): forward paper trading is the one test that cannot be
overfit, because the data did not exist when the rules were frozen. Nothing is re-implemented for "live": every evening
the frozen backtest simulation is re-run on all data to date, and the trades it enters on or after the strategy's
paper start date **are** the paper trades. The simulation is causal (tested), so these are exactly the trades it would
have made in real time. No money is involved; the user places no orders from it.

## 4. Ledger — `paper.py`

SQLite at `<data_cache_dir>/quant/paper_ledger.sqlite`, two tables:

- `trades` — keyed by strategy, symbol, entry date, expiry and strikes: credit, lot, max risk, status (`open` /
  `closed`), exit date and reason, P&L, return on risk, first seen, updated.
- `events` — integrity events.

**Integrity.** Once recorded, a trade may only change from open to closed. If a closed trade later differs, or any
recorded trade disappears, data was revised or something peeked ahead: an integrity event (`changed` /
`disappeared`) is written and the report flags it.

**Report** (`report()` → `PaperReport`): closed and open trades, mean return on risk, wins, one-sided p-value of
"mean > 0" (normal approximation), longest losing streak, and trades needed:
`max(30, ⌈(2 × backtest spread ÷ backtest mean)²⌉)`.

**Kill rules** (the Stage 3 row of the proof plan's section 5):

| Rule | Check in code |
|---|---|
| Running result below the backtest's 5th-percentile path | sum of closed results < n × mean − 1.645 × spread × √n |
| 8 losing trades in a row | `losing_streak >= 8` |
| A trade lost more than its defined max risk (pricing or rule bug) | any result < −1.10 (max risk plus 10% for costs) |
| Integrity | any integrity event |

**Verdict** for a candidate: `KILL: …` if any kill rule is hit; `PASS (Stage 3)` once trades ≥ the number needed and
p < 0.05; otherwise `collecting evidence`.

**Observation status.** A strategy with `status = "observation"` is never reported as passing, whatever its paper
results: the report says "OBSERVATION ONLY — rejected (…); not eligible for live trading" and lists any kill rules hit.
`quant_paper.py` exits 1 (failing the daily step) only when a **candidate** hits a kill rule; observation-only
strategies never fail the job.

## 5. Admitted strategies — `paper_strategies.py`

Each entry reproduces its frozen spec exactly. Changing an entry means a new strategy with a new name and start date,
never an edit in place (the ledger keys trades by strategy name).

| Field | `vrp_condor_pooled` |
|---|---|
| Spec | [../strategies/vrp_condor_pooled.md](../strategies/vrp_condor_pooled.md) |
| Parameters | NIFTY: short delta 0.25, wings 4%, z 1.5 · BANKNIFTY: short delta 0.15, wings 4%, z 0.5; 4 staggered books |
| Paper start | 2026-10-26 (frozen Friday 2026-10-23 after the close) |
| Backtest band | mean +11.1% of max risk per trade, spread 20.2% (95 trades, 2021–26; optimistic, since the settings were picked on that period) |
| Status | **observation** — "backward holdout failed: −5.6% of risk/trade 2015–21, beats random 60%" (the user's choice to keep tracking it) |

The Stage 3 targets (≥ 3 months, ≥ 50 paper trades, results inside the backtest band, slippage ≤ 1.5× model) are on
hold until a candidate passes its backtest.

```powershell
.venv\Scripts\python.exe scripts\quant_paper.py            # update every strategy and print the reports
.venv\Scripts\python.exe scripts\quant_paper.py --report   # reports only
```

User-facing docs: [../features/daily-refresh.md](../features/daily-refresh.md),
[../features/paper-trading.md](../features/paper-trading.md).
