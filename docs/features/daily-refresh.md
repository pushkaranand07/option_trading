# Daily refresh

> **Status:** Current.
> **Scope:** the after-close job that keeps the quant layer up to date.
> **Last verified against the code:** 2026-10-24

---

## 1. What it does for you

Every weekday at 19:30 the scheduled task **"TradingAgents quant daily update"** downloads the day's NSE files and
rebuilds everything that depends on them, so the next analysis and the Market Map use today's close:

download → store → volatility → regime → tracker → Market Map → paper trading → option quotes.

The first step that fails stops the run, so nothing is built on half-updated data.

## 2. How to run it

It runs on its own. To run it by hand (after about 19:00 IST, when NSE has published):

```powershell
.venv\Scripts\python.exe scripts\quant_daily_update.py --dry-run   # list the steps
.venv\Scripts\python.exe scripts\quant_daily_update.py             # run them in this window
scripts\quant_daily_update.cmd                                     # run windowless, logging to the usual file
```

Checking it ran, re-running, removing the task: [../development/scheduled-job-operations.md](../development/scheduled-job-operations.md).

## 3. Files

`scripts/quant_daily_update.py`, `scripts/quant_daily_update.cmd`, and the step scripts listed in
[../architecture/15-daily-refresh-and-paper-trading.md](../architecture/15-daily-refresh-and-paper-trading.md).

## 4. Settings

| Setting | Value |
|---|---|
| Schedule | weekdays 19:30 (Windows Task Scheduler) |
| Program | `.venv\Scripts\pythonw.exe` (no window) with `--log` |
| Task settings | start when available (catches up a missed run), run on battery |
| Data folder | `<data_cache_dir>/quant/`, by default `~/.tradingagents/cache/quant/` (`TRADINGAGENTS_CACHE_DIR` overrides) |

## 5. Outputs

- `~/.tradingagents/cache/quant/daily_status.json` — each step's exit code and seconds, and `ok`.
- `~/.tradingagents/cache/quant/daily_update.log` — full output of every run.
- Refreshed store, forecasts, regime, `docs/PROGRESS_TRACKER.md` bars, `reports/market_map/india-market-map.html`,
  paper ledger, option-quote snapshot.

## 6. Known issues

- **It runs whatever branch is checked out.** Keep `main` checked out except while working on a branch.
- Step 5 rewrites `docs/PROGRESS_TRACKER.md`, so the working tree shows it as modified after a run.
- A run before NSE publishes stores yesterday as the last day; the next run re-checks the last 10 days.
- Because the first failure stops the run, a paper-trading kill rule on a candidate strategy would also skip the option
  quotes step that night (observation-only strategies never fail the step).
