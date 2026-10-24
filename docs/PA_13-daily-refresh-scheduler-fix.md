# PA-13 — Fix the scheduled daily refresh (it never ran)

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `scripts/quant_daily_update.py`, `scripts/quant_daily_update.cmd`; Windows Task Scheduler settings on the user's machine |
| **Related** | [PA-09](PA_09-agent-quant-tool-and-lightgbm.md) · [PA-11](PA_11-ship-expected-move-and-daily-refresh.md) · [PA-12](PA_12-tracker-handoff.md) · [architecture/15-daily-refresh-and-paper-trading.md](architecture/15-daily-refresh-and-paper-trading.md) |
| **Pull request** | #12 (branch `fix/daily-refresh-scheduler`); commit `7ecbb18` |
| **Date** | 2026-10-23 |

---

## 1. Problem

The weekday 19:30 refresh registered on 23-Oct ([PA-11](PA_11-ship-expected-move-and-daily-refresh.md)) never ran,
so the quant store, forecasts and regime were not updated after the close.

## 2. Root cause / findings

1. **Path with spaces:** Task Scheduler ran `C:\coding\stock` (error 0x80070002, file not found).
2. **Default task settings:** runs were skipped on battery, and a missed start was never caught up.
3. **Visible console window:** closing it, or a Ctrl+C, killed the run (0xC000013A).

## 3. Decisions

- Run windowless with `.venv\Scripts\pythonw.exe` and a new `--log` option, so there is no window to close.
- Task settings: start when available (catch up a missed start), run on battery. Registered on the machine; no code
  change for this part.
- Each step still runs under the console `python.exe` next to `pythonw.exe`, started with `CREATE_NO_WINDOW`.

## 4. What was built / changed

| File | Change |
|---|---|
| `scripts/quant_daily_update.py` | `--log <file>` appends all output, including each step's, to the file with a timestamp header; `_python()` picks the console interpreter for steps; steps start with `CREATE_NO_WINDOW` |
| `scripts/quant_daily_update.cmd` | Same windowless command for manual runs: `pythonw.exe -W ignore scripts\quant_daily_update.py --log "%USERPROFILE%\.tradingagents\cache\quant\daily_update.log"` |

## 5. Tests

- `tests/test_quant_daily.py` passes.
- `pythonw ... --dry-run --log` writes to the log with no console.

## 6. Results

A real run started by Task Scheduler: **LastTaskResult 0, all 5 steps ok in 9.6 min**, `daily_status.json` ok, and the
23-Oct NSE files fetched.

## 7. Verification

Verified with a real scheduled run on the user's machine (PR test plan above).

## 8. Risks and open items

- The task settings live on the machine, not in the repo; re-registering the task must repeat them.
- The job runs whatever branch is checked out (tracker "Start here"), so `main` should stay checked out otherwise.
