# Audit-fix baseline (branch `fix/audit-2026-11`)

Recorded 2026-11-09, before any audit finding apart from H4 was fixed. The audit was taken at commit `0ac755a` and scored 5.4/10.

## Environment for every run

- Windows 11, Python 3.13.2 (`.venv`).
- LLM keys and Dhan keys forced empty in the environment: `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT_NAME`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`.
- `TRADINGAGENTS_NO_DOTENV=1`.
- The test suite blocks sockets (`tests/conftest.py:81`).

## Numbers

| Metric | Baseline | Notes |
|---|---|---|
| Tests | **2104 passed, 24 skipped, 1 deselected, 0 failed** | Run at `8ee9957` (H4). That's the audit's 2101 plus the 3 H4 tests. 365 s |
| Coverage (total) | **77%** (17,358 statements, 4,042 missed) | coverage.py 7.17.2, sources `webapp`, `tradingagents`, `option_backtester`, `cli` |
| `webapp/server.py` | 51% | |
| `webapp/market_data.py` | 58% (from the audit at `0ac755a`) | This run's 44% is unreliable: the file was edited for the Dhan guard while the run was in progress |
| `webapp/trade_record.py` | 97% | |
| `ruff check .` | **39 errors** | 31 F811 (tests), 2 B023, 2 F401, 1 B008, 1 E702, 1 I001, 1 SIM300. The same count at `0ac755a` and `8ee9957` |
| `pip-audit` | **No known vulnerabilities** | Run on `requirements.txt` and `webapp/requirements.txt`. The `tradingagents` package was skipped because it isn't on PyPI |
| v3 prompt fingerprint | **`5a5fdbb32e977360b8ed0c9fa45107bbd7ddc315299b825d168f79d4fbc89bd4`** | Equals the spec value. Guarded by `tests/test_fingerprint_frozen.py` |

## Data backup

`reports/` was copied to `_backup/20261109-003355/reports/`: **1,757 files, byte-identical**, with a SHA-256 manifest in `_backup/20261109-003355/MANIFEST.sha256`. It's outside git, excluded locally in `.git/info/exclude`.

## Commits so far

| Commit | What | Red → green |
|---|---|---|
| `8ee9957` fix(H4) | The package loads only `ROOT/.env`, never searching upward, and nothing under pytest or with `TRADINGAGENTS_NO_DOTENV=1` | A subprocess started from a folder whose parent has a `.env`: before, `PROBE=leaked-from-parent`; after, `PROBE=None` |
| `bed760e` feat(dhan-guard) | `webapp/dhan_guard.py`: a market-data allowlist, account endpoints blocked before sending, calls logged and rate-limited; the dead `dhan_profile()` removed | Before: an `/orders` POST and a `/profile` GET reached the HTTP layer. After: 36/36 guard tests pass, and the account paths raise before sending |
