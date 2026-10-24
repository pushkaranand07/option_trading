# Git workflow

> **Status:** Current.
> **Scope:** branches, pull requests, what may be committed, keeping the scheduled job on `main`.
> **Last verified against the code:** 2026-10-24

---

## 1. The rules

| Rule | Why |
|---|---|
| **One branch per change**, from an up-to-date `main` | each pull request is one reviewable change and one [PA record](../README.md#3-change-records-pa) |
| Branch names: `quant/<thing>`, `fix/<thing>`, `docs/<thing>` | the history reads by purpose |
| **The user merges pull requests on GitHub** | nothing reaches `main` without the user's review |
| Every pull request: tests pass (`pytest -q -m unit`), `ruff check` clean | `main` always works |
| Commit messages end with the co-author line used in this repository | attribution |
| **Never commit data or secrets** | the GitHub repository `pushkaranand07/option_trading` is **public** — see [data and secrets](data-and-secrets.md) |

## 2. Starting a change

```powershell
git checkout main
git pull
git checkout -b quant/<next-thing>
```

## 3. Finishing a change

1. Run the unit suite and ruff ([testing and lint](testing-and-lint.md)).
2. Update the [progress tracker](../PROGRESS_TRACKER.md) and run `python scripts/update_progress.py`.
3. Write the change's PA record (`docs/PA_XX-…md`, [standards](documentation-standards.md)) and add it to the index.
4. Push the branch and open a pull request; the user merges it.
5. **Switch back to `main` and pull.** The 19:30 scheduled job runs whatever branch is checked out
   ([scheduled job operations](scheduled-job-operations.md)).

## 4. Strategy specifications

A strategy's rules are committed **before** it is tested (Stage 0 of the [proof plan](../plans/PROOF_PLAN.md)): the
spec in `docs/strategies/<name>.md` is the branch's first commit and is pushed, so GitHub's timestamp proves it came
first. Any change to the rules is a new strategy and a new trial.

## 5. Long runs and parallel work

A long job (a download, a replay) runs from the checked-out branch. To work on something else meanwhile, use a second
working copy instead of switching branches under the running job:

```powershell
git worktree add "..\TradingAgents-docs" -b docs/<thing> origin/main
# ... work and commit there ...
git worktree remove "..\TradingAgents-docs"
```
