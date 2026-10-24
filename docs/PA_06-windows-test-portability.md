# PA-06 — Make three test files pass on Windows

| | |
|---|---|
| **Status** | Done (merged) |
| **Scope** | `tests/test_chatgpt_auth.py`, `tests/test_cli_updates.py`, `tests/test_suite_isolation.py` (tests only) |
| **Related** | [PA-01](PA_01-india-market-intelligence-baseline.md) · [PA-07](PA_07-option-backtester-exit-fixes.md) |
| **Pull request** | #5 (branch `fix/windows-test-portability`); commit `ce1500a` |
| **Date** | 2026-10-23 |

---

## 1. Problem

The suite had 5 failures on Windows, present since the initial import (recorded in
[plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md](plans/INDIA_MARKET_INTELLIGENCE_BUILD_PLAN.md) section 13 as
"5 pre-existing failures in ChatGPT-auth, CLI-update and yfinance-cache tests"). They were on the bug-fix list the
user asked for on 2026-10-23 (tracker).

## 2. Root cause / findings

The tests assumed POSIX behaviour; the product code was correct on Windows.

| Test file | Cause |
|---|---|
| `test_chatgpt_auth.py` | Asserted file mode `0600`; Windows has no mode bits (the file is created with `0o600` and lives in the user's own profile) |
| `test_cli_updates.py` | The upgrade command is POSIX shell; `upgrade_command()` returns `None` on Windows by design |
| `test_suite_isolation.py` | Checked that yfinance's tz cache is outside the home folder; on Windows the temp dir is itself under home |

## 3. Decisions

- Fix the tests, not the code: assert the mode only on POSIX; skip the two POSIX upgrade tests on Windows and test the
  Windows behaviour instead; check the cache is in the temp directory the suite created.

## 4. What was built / changed

3 test files, 24 lines added, 4 removed. No product code changed.

## 5. Tests

The changed tests themselves.

## 6. Results

Full suite on Windows: **1423 passed, 6 skipped, 0 failed** (commit message / PR body).

## 7. Verification

Full suite run on the user's Windows machine.

## 8. Risks and open items

None recorded.
