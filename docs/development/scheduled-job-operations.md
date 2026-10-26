# Scheduled job operations

> **Status:** Current.
> **Scope:** operating the Windows scheduled task "TradingAgents quant daily update" (`scripts/quant_daily_update.py`).
> **Last verified against the code:** 2026-10-24

---

## 1. What runs

Weekdays at 19:30, Task Scheduler runs, from the repository root:

```
.venv\Scripts\pythonw.exe -W ignore scripts\quant_daily_update.py --log %USERPROFILE%\.tradingagents\cache\quant\daily_update.log
```

Eight steps in order (download → store → volatility → regime → tracker → market_map → paper → quotes); the first
failure stops the run. Design and setup: [../architecture/15-daily-refresh-and-paper-trading.md](../architecture/15-daily-refresh-and-paper-trading.md).

**Morning plan** — weekdays at **08:30**, task "TradingAgents morning plan" ([PA-22](../PA_22-morning-plan.md)):

```
.venv\Scripts\pythonw.exe -W ignore scripts\morning_plan.py --log %USERPROFILE%\.tradingagents\cache\quant\morning_plan.log
```

Builds `reports/morning/<date>.json` for NIFTY and BANKNIFTY (data + two GPT-5 analyses, ~20 min); on holidays it
records the closure and skips the AI. Check: `schtasks /Query /TN "TradingAgents morning plan" /V /FO LIST`; run now:
`schtasks /Run /TN "TradingAgents morning plan"`; remove: `schtasks /Delete /TN "TradingAgents morning plan" /F`.
Like the nightly job it runs the checked-out branch and needs the PC on and the user logged in.

## 2. Checking it ran

**Status file** — `~/.tradingagents/cache/quant/daily_status.json`:

```powershell
Get-Content "$env:USERPROFILE\.tradingagents\cache\quant\daily_status.json"
```

- `started` / `finished` should be this evening.
- `ok: true` means all 8 steps ran and exited 0.
- On a failure, the last entry in `steps` is the step that stopped the run, with its `exit_code`.
- The file is written only when the job gets as far as running steps; if it is stale, the task did not start or the
  job crashed first — check the log and the task's history.

**Log** — `~/.tradingagents/cache/quant/daily_update.log`. Each run starts with a `==== <timestamp>` line, each step
with `=== scripts/<step>.py ...`, and the run ends with `Daily update finished -> …` or `Daily update STOPPED at <step> -> …`.

```powershell
Get-Content "$env:USERPROFILE\.tradingagents\cache\quant\daily_update.log" -Tail 60
```

**Task Scheduler** — last run time and result:

```powershell
schtasks /Query /TN "TradingAgents quant daily update" /V /FO LIST
```

Result `0x0` is success. Two codes seen before the PR #12 fix: `0x80070002` (the path with a space was split) and
`0xC000013A` (a console window was closed mid-run).

## 3. Re-running by hand

After about 19:00 IST (NSE publishes the day's files in the evening):

```powershell
scripts\quant_daily_update.cmd                                    # same as the task: windowless, appends to the log
.venv\Scripts\python.exe scripts\quant_daily_update.py            # in this window, output on screen
.venv\Scripts\python.exe scripts\quant_daily_update.py --dry-run  # list the steps without running them
schtasks /Run /TN "TradingAgents quant daily update"              # start the scheduled task now
```

To redo one step after fixing its cause, run that step's script directly (the commands are in the architecture
document), then the steps after it. Re-running the whole job is safe: downloads skip finished files, store years are
replaced whole, and the paper ledger only records new or newly closed trades.

## 4. Keep `main` checked out

**The job runs whatever branch is checked out** in the repository folder. Work on a feature branch at 19:30 and the job
runs that branch's code, and step 5 rewrites `docs/PROGRESS_TRACKER.md` in that working tree. Keep `main` checked out
when not actively working; for new work:

```powershell
git checkout main
git pull
git checkout -b quant/<next-thing>
```

## 5. Removing the task

```powershell
schtasks /Delete /TN "TradingAgents quant daily update" /F
```

This removes only the schedule; data under `~/.tradingagents/cache/quant/` stays. Re-creating it:
[../architecture/15-daily-refresh-and-paper-trading.md](../architecture/15-daily-refresh-and-paper-trading.md), section 2.
