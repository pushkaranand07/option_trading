# Forward test backup and restore

> **Status:** Written 2026-11-01. The backup runs by hand only, with no schedule and no upload.
> **Scope:** `reports/ai_test/`: `registry.jsonl`, `chains/` and `power.json`. That folder is gitignored, so git does not protect it.

## Back up

```
python scripts/ai_test_backup.py --dest "<folder you chose>"
```

This makes `ai_test_backup_<date>_<time>` inside that folder, with `SHA256SUMS.txt`, and checks every file after copying. It refuses a destination inside the repo and never overwrites an earlier backup.

If the destination is a cloud-synced folder such as OneDrive, the sync app uploads it, and the chains and registry leave this machine.

## Check a backup

```
python scripts/ai_test_backup.py --verify "<backup folder>"
```

It prints `OK`, or lists each missing, changed or extra file.

## Restore

1. Check the backup, as above. Do not restore one that fails.
2. Stop the web app, so nothing writes to the registry.
3. Rename the current `reports/ai_test` to `reports/ai_test_before_restore`. Do not delete it.
4. Copy `registry.jsonl`, `chains` and `power.json` from the backup into a new `reports/ai_test`.
5. Check the hash chain:

```
python -c "from pathlib import Path; from tradingagents.research import registry; print(registry.verify(Path('reports/ai_test/registry.jsonl')))"
```

It prints the row count, or raises an error if the chain is broken.

## What a restore costs the test

Rows written after the backup are lost. The days they covered cannot be filled in later, because a session is registered only on that session. They are recorded as missed.
