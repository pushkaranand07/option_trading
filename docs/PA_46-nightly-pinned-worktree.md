# PA-46 — Nightly job pinned to main in a dedicated worktree

| | |
|---|---|
| **Status** | Code in this pull request. **The scheduled task changes only after the merge**: `python scripts/nightly_pinned.py --install` |
| **Scope** | new `scripts/nightly_pinned.py`, `tests/test_nightly_pinned.py`; `scripts/market_map.py` |
| **Related** | [data catalog](data_catalog.md) |
| **Pull request** | branch `ops/nightly-pinned-worktree` |
| **Date** | 2026-10-31 |

## 1. Problem

The task ran from the main checkout. On 2026-10-31 at 10:12 it started while that checkout was on a research branch, so it ran that branch's code. What it collects does not change here.

## 2. How it is pinned

| Part | What it does |
|---|---|
| Worktree | `C:\coding\stock market\TradingAgents-nightly`, a linked git worktree with a detached HEAD |
| Before each run | Fetches `origin main` and moves the worktree to `origin/main`, discarding local changes there |
| Check | Refuses to run, with exit 2 and a log line, unless it is a linked worktree, detached, and exactly at `origin/main` |
| Failed fetch | Runs the last main commit it holds and logs it, so an internet problem does not skip the run |
| Imports | `PYTHONPATH` puts the worktree first, ahead of the editable install that points at the main checkout |
| Python | The main checkout's `.venv`. Packages are not branch-specific; a dependency added on main still needs installing there |
| Log line | Each run logs the commit it runs |

## 3. What stays in the main checkout

| Item | How |
|---|---|
| `.env` | Read from the main checkout at run time, never copied |
| `reports/market_map/` | `TRADINGAGENTS_REPORTS_DIR` points at the main checkout's `reports/`, where the web app reads it. Without the variable, the path is as before |
| Store and logs | Already under the user's home folder |

## 4. Behaviour changes

- **`docs/PROGRESS_TRACKER.md` no longer changes in the main checkout.** The tracker step still runs, but in the worktree, and that copy is discarded at the next run. The tracker in the main checkout updates only when `update_progress.py` is run there.
- **Merged changes go live at the next run,** without anyone switching branches.

## 5. Tests

`tests/test_nightly_pinned.py` builds a real origin, checkout and worktree: a research branch or uncommitted work in the main checkout does not change what runs; each run moves to the latest main; a failed fetch runs the last commit and says so; the main checkout, a branch and an off-main commit are refused; `.env` and `reports/` come from the main checkout, with no copy.

## 6. Not changed

The morning plan task ("TradingAgents morning plan", 08:30) still runs from the main checkout and has the same exposure. It was not in scope.

Why the 2026-10-30 19:30 run is missing from the log is not addressed here; the user will report it.
